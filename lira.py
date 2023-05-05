import json
import logging
from pymed import PubMed

logging.basicConfig(level=logging.INFO)  # init logging

pubmed = PubMed(tool="LiRA", email="franco.pradelli94@gmail.com")  # init pubmed

# init html
outfile = "literature_review_report.html"
literature_review_report = f'<!-- {outfile} -->\n' \
                           '\n' \
                           '<!DOCTYPE html>\n' \
                           '<html lang="en">\n' \
                           '<head>\n' \
                               '<meta charset="utf-8">\n' \
                               '<title>LiRA output</title>\n' \
                           '</head>\n' \
                           '<body>\n'

# insert initial date for literature Review
initial_date = input("Insert initial date for literature review (AAAA/MM/DD): ")

# load keywords
with open("keywords.json", "r") as infile:
    keywords = json.load(infile)

# get journals
my_journals = keywords["my_journals"]

# get authors
authors = keywords["authors"]
my_authors = keywords["my_authors"]
authors += my_authors

# iterate on journals
for journal in my_journals:
    # get how many papers where published in total
    query = f'(("{initial_date}"[Date - Create] : "3000"[Date - Create])) AND ({journal}[Journal])'
    logging.info(f"Running query: {query}")
    results = pubmed.query(query, max_results=1000)
    n_tot_results = len(list(results))
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
            lambda a: any([(str(a['lastname']) in author) and (str(a['firstname']) in author) for author in authors]),
            article_authors))

        # if any, add them to the string in bold
        if interesting_authors:
            interesting_authors_string = ", ".join([f"<strong>{ia}</strong>" for ia in interesting_authors])
            authors_string += interesting_authors_string

        # finish author sting
        authors_string += f"et al. ({({article.publication_date})})"

        # add other information
        literature_review_report += f"<p><em>{authors_string}</em></p>\n"
        literature_review_report += f"<p><strong>{article.title}</strong></p>\n"
        article_id = str(article.pubmed_id).split("\n")[0]  # get pubmed id
        literature_review_report += f'<p><a href="https://pubmed.ncbi.nlm.nih.gov/{article_id}/">' \
                                    f'https://pubmed.ncbi.nlm.nih.gov/{article_id}</a></p>\n'
        literature_review_report += f"<p>{article.abstract}</p>\n"
        literature_review_report += f"<p> ------------------------------------------------------ </p>\n"

# write report
with open(outfile, "w") as html_file:
    logging.info("Saving report... ")
    html_file.write(literature_review_report)
    logging.info("Done.")
