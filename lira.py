import json
import logging
import argparse
import webbrowser
from pathlib import Path
from pymed import PubMed
from typing import Dict, List
from datetime import datetime, timedelta


""" Initialize logger """
logger = logging.getLogger(__name__)
handler = logging.StreamHandler()
handler.setLevel(logging.INFO)
formatter = logging.Formatter("%(levelname)s:%(name)s: %(message)s")
handler.setFormatter(formatter)
logger.addHandler(handler)

""" Macros definition """
CONFIG_FOLDER = Path("config")
DEFAULT_CONFIG_FILE = CONFIG_FOLDER / Path("config.json")
OUT_FOLDER = Path("out")
OUT_HTML = OUT_FOLDER / Path("lira_output.html")
DEFAULT_PYMED_MAX_RESULTS = 500


def init_parser() -> argparse.Namespace:
    """
    Parse CLI arguments

    :return: CLI arguments as namespace
    """
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
                        help="Define a configuration file to use instead of the default config.json.")

    # add option for silence
    parser.add_argument("--quiet", "-q",
                        action='store_true',
                        help="Avoid printing log messages")

    # add methods to filter outputs
    parser.add_argument("--filter-journals", "-fj",
                        action="store_true",
                        help="Use Keywords to filter journal results")
    parser.add_argument("--filter-authors", "-fa",
                        action='store_true',
                        help="Use Keywords to filter authors results")

    # add methods to suppress output
    parser.add_argument("--suppress-general", "-sg",
                        action='store_true',
                        help='Do not add to the output the Pubmed results obtained with the keywords')

    # add '--max_results_for_query' to update the maximum number of results
    parser.add_argument("--max-results-for-query",
                        type=int,
                        help=f"Change the maximum number of results for each executed query. Default is "
                             f"{DEFAULT_PYMED_MAX_RESULTS}.\n"
                             f"Notice: the higher this value is, the higher will be the time to perform the search.")
    return parser.parse_args()


def init_lira():
    """
    Initialize LiRA for the first usage.

    :return:
    """
    # create config folder if it does not exist
    CONFIG_FOLDER.mkdir(exist_ok=True)

    # check if config file exists;
    # if not, raise error
    if not DEFAULT_CONFIG_FILE.exists():
        raise RuntimeError(f"Configuration file not found. To work with LiRA, create a default "
                           f"configuration file config/config.json.")

    # generate output folder if it does not exist
    OUT_FOLDER.mkdir(exist_ok=True)


def add_keywords_to_query(query: str,
                          config: Dict[str, str]):
    all_keywords = " OR ".join([f"({keyword})" for keyword in config["keywords"]])
    query += f" AND ({all_keywords})"
    return query


def make_pubmed_query(pubmed: PubMed,
                      query: str,
                      args: argparse.Namespace):
    # get max results for query
    max_results_for_query = get_max_results_for_query(args)
    # run search
    logger.info(f"Running query (max res: {max_results_for_query}): {query}")
    results = pubmed.query(query, max_results=max_results_for_query)

    return results


def read_config(args: argparse.Namespace) -> Dict:
    """
    Read configuration file

    :param args:
    :return:
    """
    # get config file
    if args.config is None:
        config_file = DEFAULT_CONFIG_FILE
    else:
        config_file = Path(args.config)

    # read config file
    with open(config_file, "r") as infile:
        config = json.load(infile)

    return config


def get_max_results_for_query(args: argparse.Namespace):
    if args.max_results_for_query is not None:
        max_results_for_query = args.max_results_for_query
    else:
        max_results_for_query = DEFAULT_PYMED_MAX_RESULTS
    return max_results_for_query


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
    if len(article_authors) > 0:
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
    else:
        authors_string = f"None {article.publication_date.strftime('%d/%m/%Y')}"

    # add other information
    literature_review_report += f'<p class="lorem" style="font-size: larger;"><strong>{article.title}</strong></p>\n'
    literature_review_report += f'<p class="lorem">{authors_string}</em><br>\n'
    article_id = str(article.pubmed_id).split("\n")[0]  # get pubmed id
    literature_review_report += f'<a href="https://pubmed.ncbi.nlm.nih.gov/{article_id}/">' \
                                f'https://pubmed.ncbi.nlm.nih.gov/{article_id}</a><br>\n'
    literature_review_report += f'{article.abstract}</p>\n'
    literature_review_report += f'<hr class="lorem">\n'

    return literature_review_report


def search_for_keywords(literature_review_report: str,
                        config: Dict,
                        pubmed: PubMed,
                        args: argparse.Namespace):
    """
    Search the keywords in PubMed

    :param literature_review_report:
    :param config:
    :param pubmed:
    :param args:
    :return:
    """
    # get authors
    authors = config["highlight_authors"]
    my_authors = config["authors"]
    authors += my_authors

    # get initial date
    initial_date = get_initial_date(args)

    # init query with date
    query = f'(("{initial_date}"[Date - Create] : "3000"[Date - Create]))'
    # add keywords to the query
    query = add_keywords_to_query(query, config)
    results = make_pubmed_query(pubmed, query, args)

    # save to partial_report
    partial_report = ""
    n_results = 0
    for article in results:
        partial_report = update_report(partial_report, article, authors)
        n_results += 1

    # save result to html
    literature_review_report += f"<h1>General results " \
                                f"({n_results}) " \
                                f"({initial_date} - {datetime.now().strftime('%Y/%m/%d')})</h1>\n"
    literature_review_report += partial_report
    return literature_review_report


def search_for_journal(literature_review_report: str,
                       config: Dict,
                       pubmed: PubMed,
                       args: argparse.Namespace):
    # get journals
    my_journals = config["journals"]

    # check number of journals
    if len(my_journals) == 0:
        logger.info("No Journals found")
        return literature_review_report
    else:
        # get authors
        authors = config["highlight_authors"]
        my_authors = config["authors"]
        authors += my_authors

        # get initial date
        initial_date = get_initial_date(args)

        # get max results for query
        max_results_for_query = get_max_results_for_query(args)

        # iterate on journals
        for journal in my_journals:
            # get how many papers where published in total in the journal
            query = f'(("{initial_date}"[Date - Create] : "3000"[Date - Create])) AND ({journal}[Journal])'
            results = make_pubmed_query(pubmed, query, args)
            n_tot_results = sum(1 for _ in results)
            if n_tot_results == max_results_for_query:
                logger.warning(f"Number of paper published might exceed {max_results_for_query}. "
                               f"Consider changing the max results for query using the flag '--max_results_for_query'.")
            logger.info(f"Found total papers published on {journal}: {n_tot_results}")

            # if necessary, add keywords to the query
            if args.filter_journals:
                query = add_keywords_to_query(query, config)

            # run query
            results = make_pubmed_query(pubmed, query, args)

            # save to partial_report
            partial_report = ""
            n_results = 0
            for article in results:
                partial_report = update_report(partial_report, article, authors)
                n_results += 1

            if args.filter_journals:
                n_results_str = f"({n_results}/{n_tot_results})"
            else:
                n_results_str = f"({n_results})"

            # save result to html
            literature_review_report += f"<h1>Results from {journal} " \
                                        f"{n_results_str} " \
                                        f"({initial_date} - {datetime.now().strftime('%Y/%m/%d')})</h1>\n"
            literature_review_report += partial_report

        return literature_review_report


def search_for_authors(literature_review_report: str, config: Dict, pubmed: PubMed, args):
    # get authors
    authors = config["highlight_authors"]
    my_authors = config["authors"]
    authors += my_authors

    # check number of authors
    if len(my_authors) == 0:
        logger.info("No authors found.")
        return literature_review_report

    # get initial date
    initial_date = get_initial_date(args)

    # generate authors query
    query = f'(("{initial_date}"[Date - Create] : "3000"[Date - Create]))'
    all_authors = " OR ".join([f"({author.replace(',', '')}[Author])" for author in config["authors"]])
    query = f"{query} AND ({all_authors})"

    # make unfiltered query
    results = make_pubmed_query(pubmed, query, args)

    # get max results for query
    max_results_for_query = get_max_results_for_query(args)

    # count total number of results
    n_tot_results = sum(1 for _ in results)
    if n_tot_results == max_results_for_query:
        logger.warning(f"Number of paper published might exceed {max_results_for_query}. "
                       f"Consider changing the max results for query using the flag '--max_results_for_query'.")
    logger.info(f"Found total papers published for authors: {n_tot_results}")

    # if necessary, filter authors
    if args.filter_authors:
        query = add_keywords_to_query(query, config)

    # make query
    results = make_pubmed_query(pubmed, query, args)

    # create partial reports
    n_results = 0
    partial_report = ""
    for article in results:
        partial_report = update_report(partial_report, article, authors)
        n_results += 1

    if args.filter_journals:
        n_results_str = f"({n_results}/{n_tot_results})"
    else:
        n_results_str = f"({n_results})"

    # init new section
    literature_review_report += f"<h1>Results from Authors " \
                                f"{n_results_str} " \
                                f"({initial_date} - {datetime.now().strftime('%Y/%m/%d')})</h1>\n"

    # add articles
    literature_review_report += partial_report

    return literature_review_report


def run_search(args, config):
    """
    Run literature research with PubMed.
    """
    pubmed = PubMed(tool="LiRA", email=config["email"])  # init pubmed

    # open template html
    with open("in/template.html", "r") as infile:
        template = infile.read()
    literature_review_report = ""

    # Generate the 'general' part using keywords
    if not args.suppress_general:
        literature_review_report = search_for_keywords(literature_review_report, config, pubmed, args)

    # Generate the journals part
    literature_review_report = search_for_journal(literature_review_report, config, pubmed, args)

    # search for authors
    literature_review_report = search_for_authors(literature_review_report, config, pubmed, args)

    # check if literature review is empty
    if literature_review_report == "":
        logger.warning(f"LiRA output is empty.")

    # replace text in template
    literature_review_report = template.replace("TO_REPLACE", literature_review_report)

    # write report
    with open(OUT_HTML, "w") as html_file:
        logger.info("Saving HTML report... ")
        html_file.write(literature_review_report)
        logger.info("Done.")


def main():
    # parse arguments from cli
    args = init_parser()

    # initialize LiRA
    init_lira()

    # get config file
    config = read_config(args)

    # manage log
    log_level = logging.WARNING if args.quiet else logging.INFO
    logger.setLevel(log_level)

    # if args.last is true, check if OUT_HTML exists; else run_search
    if args.last:
        assert OUT_HTML.exists(), f"Last LiRA output not found. Should be in {OUT_HTML.resolve()}"
    else:
        run_search(args, config)

    # open result in browser
    webbrowser.open(url=str(OUT_HTML.resolve()), new=0)


if __name__ == "__main__":
    main()
