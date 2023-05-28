import json
import logging
from pymed import PubMed
from typing import Dict
import argparse
import datetime


def init_parser():
    # init parser
    parser = argparse.ArgumentParser(description="LiRA: Literature Review Automated. "
                                                 "Based on pymed to query PubMed programmatically. ")
    parser.add_argument("--from_date", "-d",
                        type=str,
                        help="Date from which the Literature Review should start, in format AAAA/MM/DD",
                        required=True)

    return parser.parse_args()


def search_for_journal(literature_review_report: str, keywords: Dict, pubmed: PubMed, args):
    # get journals
    my_journals = keywords["my_journals"]

    # get authors
    authors = keywords["authors"]
    my_authors = keywords["my_authors"]
    authors += my_authors

    # get initial date
    initial_date = args.from_date

    # iterate on journals
    for journal in my_journals:
        # get how many papers where published in total
        query = f'(("{initial_date}"[Date - Create] : "3000"[Date - Create])) AND ({journal}[Journal])'
        logging.info(f"Running query: {query}")
        results = pubmed.query(query, max_results=1000)
        n_tot_results = sum(1 for _ in results)
        if n_tot_results == 1000:
            logging.warning(f"Number of paper published might exceed 1000. Consider changing the query.")
        logging.info(f"Found total papers published on {journal}: {n_tot_results}")

        # get all the papers matching the keywords
        allkeywords = " OR ".join([f"({keyword})" for keyword in keywords["searches"]])
        query += f" AND ({allkeywords})"
        logging.info(f"Running query: {query}")
        results = list(pubmed.query(query, max_results=500))

        # save result to html
        literature_review_report += f"<h1>Results from {journal} ({len(results)}/{n_tot_results})</h1>\n"
        for article in results:
            # manage authors
            article_authors = article.authors  # get authors
            first_author = article_authors[0]  # get first
            authors_string = f"{first_author['lastname']}, {first_author['firstname']}, "  # init authors string

            # parse if any of the authors is one of the authors followed by the lab
            interesting_authors = list(filter(
                lambda a: any(
                    [(str(a['lastname']) in author) and (str(a['firstname']) in author) for author in authors]),
                article_authors))

            # if any, add them to the string in red
            if interesting_authors:
                interesting_authors_string = ", ...".join(
                    [f'<span style="color: #ff0000">{ia["lastname"]}, {ia["firstname"]}</span> ' for ia in
                     interesting_authors])
                authors_string += interesting_authors_string

            # finish author sting
            authors_string += f"et al. ({article.publication_date.strftime('%d/%m/%Y')})"

            # add other information
            literature_review_report += f'<p class="lorem" style="font-size: larger;"><strong>{article.title}</strong></p>\n'
            literature_review_report += f'<p class="lorem">{authors_string}</em><br>\n'
            article_id = str(article.pubmed_id).split("\n")[0]  # get pubmed id
            literature_review_report += f'<a href="https://pubmed.ncbi.nlm.nih.gov/{article_id}/">' \
                                        f'https://pubmed.ncbi.nlm.nih.gov/{article_id}</a><br>\n'
            literature_review_report += f'{article.abstract}</p>\n'
            literature_review_report += f'<hr class="lorem">\n'

    return literature_review_report


def main():
    logging.basicConfig(level=logging.INFO)  # init logging

    pubmed = PubMed(tool="LiRA", email="franco.pradelli94@gmail.com")  # init pubmed

    # init html
    outfile = "out/output.html"
    with open("in/template.html", "r") as infile:
        template = infile.read()
    literature_review_report = ""

    # parse arguments from cli
    args = init_parser()

    # load keywords
    with open("keywords.json", "r") as infile:
        keywords = json.load(infile)

    # search in journals
    literature_review_report = search_for_journal(literature_review_report, keywords, pubmed, args)

    # replace text in template
    literature_review_report = template.replace("TO_REPLACE", literature_review_report)

    # write report
    with open(outfile, "w") as html_file:
        logging.info("Saving report... ")
        html_file.write(literature_review_report)
        logging.info("Done.")


if __name__ == "__main__":
    main()
