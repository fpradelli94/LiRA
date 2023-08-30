import json
import logging
from pathlib import Path
from pymed import PubMed
from typing import Dict, List
import argparse
from datetime import datetime, timedelta
import webbrowser
import re


def init_parser():
    # init parser
    parser = argparse.ArgumentParser(description="LiRA: Literature Review Automated. "
                                                 "Based on pymed to query PubMed programmatically. ")
    # add mutually exclusive group for arguments
    group = parser.add_mutually_exclusive_group(required=True)
    # insert day from which the research start
    group.add_argument("--from-date", "-d",
                       type=str,
                       help="Date from which the Literature Review should start, in format AAAA/MM/DD")
    group.add_argument("--for-weeks", "-w",
                       type=int,
                       help="Number of weeks for the literature review. LiRA will search for the n past weeks")
    # add see last output
    group.add_argument("--last", "-L",
                       action='store_true',
                       help="Just opens the last LiRA output without running a search")
    # get option for configuration file
    parser.add_argument("--config", "-c",
                        type=str,
                        help="Define a configuration file to use in place of the default.")
    # add option for silence
    parser.add_argument("--silent", "-s",
                        action='store_true',
                        help="Avoid printing log messages")
    return parser.parse_args()


def init_lira(args):
    # create base folder if it does not exist
    base_folder = Path.home() / Path(".buplira")
    base_folder.mkdir(exist_ok=True)

    # get config file
    if args.config is None:
        config_file = base_folder / Path("config.json")
    else:
        config_file = Path(args.config)

    # check if config file exists
    if config_file.exists():
        with open(config_file, "r") as infile:
            config = json.load(infile)
    else:
        # get template
        with open("in/template_config.json", "r") as infile:
            config = json.load(infile)
        # insert valid email
        email = ""
        email_regex = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,7}\b'
        while not re.fullmatch(email_regex, email):
            email = input("Insert valid email (necessary for PyMed queries): ")
        config["email"] = email
        # write config file
        with open(config_file, "w") as outfile:
            json.dump(config, outfile)
        # get warning
        logging.warning("config.json file was just created and it's empty. You should fill it before using LiRA")

    # generate output folder if it does not exist
    out_folder = base_folder / Path("out")
    out_folder.mkdir(exist_ok=True)

    return config, out_folder


def get_initial_date(args):
    if args.from_date is None:
        initial_date = datetime.now() - timedelta(weeks=args.for_weeks)
        initial_date = initial_date.strftime("%Y/%m/%d")
    else:
        initial_date = args.from_date
    return initial_date


def update_report(literature_review_report: str, article, authors: List[str]):
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


def search_for_keywords(literature_review_report: str, config: Dict, pubmed: PubMed, args):
    # get authors
    authors = config["authors"]
    my_authors = config["my_authors"]
    authors += my_authors

    # get initial date
    initial_date = get_initial_date(args)

    # init query with date
    query = f'(("{initial_date}"[Date - Create] : "3000"[Date - Create]))'
    # add keywords to the query
    all_keywords = " OR ".join([f"({keyword})" for keyword in config["searches"]])
    query += f" AND ({all_keywords})"
    # run search
    logging.info(f"Running query: {query}")
    results = pubmed.query(query, max_results=500)

    # save to partial_report
    partial_report = ""
    n_results = 0
    for article in results:
        partial_report = update_report(partial_report, article, authors)
        n_results += 1

    # save result to html
    literature_review_report += f"<h1>Results " \
                                f"({n_results}) " \
                                f"({initial_date} - {datetime.now().strftime('%Y/%m/%d')})</h1>\n"
    literature_review_report += partial_report


    return literature_review_report


def search_for_journal(literature_review_report: str, config: Dict, pubmed: PubMed, args):
    # get journals
    my_journals = config["my_journals"]

    # get authors
    authors = config["authors"]
    my_authors = config["my_authors"]
    authors += my_authors

    # get initial date
    initial_date = get_initial_date(args)

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
        all_keywords = " OR ".join([f"({keyword})" for keyword in config["searches"]])
        query += f" AND ({all_keywords})"
        logging.info(f"Running query: {query}")
        results = pubmed.query(query, max_results=500)

        # save to partial_report
        partial_report = ""
        n_results = 0
        for article in results:
            partial_report = update_report(partial_report, article, authors)
            n_results += 1

        # save result to html
        literature_review_report += f"<h1>Results from {journal} " \
                                    f"({n_results}/{n_tot_results}) " \
                                    f"({initial_date} - {datetime.now().strftime('%Y/%m/%d')})</h1>\n"
        literature_review_report += partial_report

    return literature_review_report


def search_for_authors(literature_review_report: str, config: Dict, pubmed: PubMed, args):
    # get authors
    authors = config["authors"]
    my_authors = config["my_authors"]
    authors += my_authors

    # get initial date
    initial_date = get_initial_date(args)

    for author in my_authors:
        pubmed_author_string = author.replace(",", "")  # remove comma for pubmed search

        # make query
        query = f'(("{initial_date}"[Date - Create] : "3000"[Date - Create])) AND ({pubmed_author_string}[Author])'
        logging.info(f"Running query: {query}")
        results = pubmed.query(query, max_results=1000)

        # create partial reports
        n_tot_results = 0
        partial_report = ""
        for article in results:
            partial_report = update_report(partial_report, article, authors)
            n_tot_results += 1

        # init new section
        literature_review_report += f"<h1>Results from {author} " \
                                    f"({n_tot_results}) " \
                                    f"({initial_date} - {datetime.now().strftime('%Y/%m/%d')})</h1>\n"

        # add articles
        literature_review_report += partial_report

    return literature_review_report


def run_search(args, config, out_folder):
    """
    Run literature reserarch.
    """
    pubmed = PubMed(tool="LiRA", email=config["email"])  # init pubmed

    # init html
    lira_output = out_folder / Path("output.html")

    # open template html
    with open("in/template.html", "r") as infile:
        template = infile.read()
    literature_review_report = ""

    # if the journals list is empty, search for simple strings
    if len(config["my_journals"]) == 0:
        literature_review_report = search_for_keywords(literature_review_report, config, pubmed, args)

    # search in journals
    literature_review_report = search_for_journal(literature_review_report, config, pubmed, args)

    # search for authors
    literature_review_report = search_for_authors(literature_review_report, config, pubmed, args)

    # check if literature review is empty
    if literature_review_report == "":
        logging.warning(f"LiRA output looks empty.")

    # replace text in template
    literature_review_report = template.replace("TO_REPLACE", literature_review_report)

    # write report
    with open(lira_output, "w") as html_file:
        logging.info("Saving report... ")
        html_file.write(literature_review_report)
        logging.info("Done.")


def main():
    # parse arguments from cli
    args = init_parser()

    # manage initialization
    config, out_folder = init_lira(args)

    # manage log
    log_level = logging.WARNING if args.silent else logging.INFO
    logging.basicConfig(level=log_level)

    # check if necessary to run search
    lira_output_html = out_folder / Path("output.html")
    if args.last:
        assert lira_output_html.exists(), f"Last LiRA output not found. Should be in {lira_output_html.resolve()}"
    else:
        run_search(args, config, out_folder)

    # open result in browser
    webbrowser.open(url=str(lira_output_html), new=0)


if __name__ == "__main__":
    main()
