import json
import logging
import argparse
import requests
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


def parse_cli_args() -> argparse.Namespace:
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


class LiRA:
    def __init__(self):
        # generate folders
        CONFIG_FOLDER.mkdir(exist_ok=True)  # generate config folder
        OUT_FOLDER.mkdir(exist_ok=True)  # generate out folder

        # check if config file exists
        assert DEFAULT_CONFIG_FILE.exists(), f"Configuration file not found. To work with LiRA, create a default " \
                                             f"configuration file config/config.json."

        # parse CLI arguments
        self.args = parse_cli_args()
        # get max results for search
        if self.args.max_results_for_query is None:
            self.max_results_for_query = DEFAULT_PYMED_MAX_RESULTS
        else:
            self.max_results_for_query = self.args.max_results_for_query
        # get initial date
        date_format = "%Y/%m/%d"
        if self.args.from_date is None:
            initial_date = datetime.now() - timedelta(weeks=self.args.for_weeks)
            self.initial_date = initial_date.strftime(date_format)
        else:
            self.initial_date = self.args.from_date
        # get time delta between now and initial date
        time_range: timedelta = datetime.now() - datetime.strptime(self.initial_date, date_format)
        self.timedelta_days = time_range.days

        # manage log
        log_level = logging.WARNING if self.args.quiet else logging.INFO
        logger.setLevel(log_level)

        # read config
        config = read_config(self.args)
        # load config as properties
        self.email = config["email"]
        self.serpapi_key = config["serpapi_key"]
        self.keywords = config["keywords"]
        self.journals = config["journals"]
        self.authors = config["authors"]
        self.highlight_authors = config["highlight_authors"] + self.authors

        # init pymed
        self.pubmed = PubMed(tool="LiRA", email=self.email)

        # create base url for google scholar
        self.gs_base_url = "https://serpapi.com/search?engine=google_scholar"

        # init base request parameters for google scholar
        self.gs_parameters = {
            "api_key": self.serpapi_key,
            "scisbd": 2,  # get results from most recent
            "num": self.max_results_for_query
        }

    def _get_authors_to_highlight_from_list(self, list_of_authors: List):
        authors_to_highlight = list(filter(
            lambda a: any([(str(a['lastname']) in ha) and (str(a['firstname']) in ha)
                           for ha in self.highlight_authors]),
            list_of_authors
        ))
        return authors_to_highlight

    def _pubmed_add_keywords_to_query(self, query: str):
        keywords_query = " OR ".join([f"({keyword})" for keyword in self.keywords])
        query += f" AND ({keywords_query})"
        return query

    def pubmed_make_query(self, query: str):
        logger.info(f"Running PubMed query (max res: {self.max_results_for_query}): {query}")
        results = self.pubmed.query(query, max_results=self.max_results_for_query)

        return results

    def _pubmed_get_partial_report_from_results(self, results):
        partial_report = ""  # init partial report
        n_results = 0  # init n_results

        for article in results:
            n_results += 1  # update n_results

            # generate 'authors string', i.e. a string containing the first author of the paper and any other
            # author in the list self.highlight authors
            article_authors = article.authors  # get authors
            if len(article_authors) > 0:
                first_author = article_authors[0]  # get first name
                authors_string = f"{first_author['lastname']}, {first_author['firstname']}, "  # add to authors string

                # highlight authors
                authors_to_highlight = self._get_authors_to_highlight_from_list(article_authors)

                # if any, add them to the string in red
                if authors_to_highlight:
                    authors_to_highlight_string = ", ...".join(
                        [f'<span style="color: #ff0000">{ia["lastname"]}, {ia["firstname"]}</span> ' for ia in
                         authors_to_highlight])
                    authors_string += authors_to_highlight_string

                # finish author sting
                authors_string += f"et al. ({article.publication_date.strftime('%d/%m/%Y')})"
            else:
                authors_string = f"None {article.publication_date.strftime('%d/%m/%Y')}"

            # add publication info to partial report
            # 1. paper title
            partial_report += f'<p class="lorem" style="font-size: larger;"><strong>{article.title}</strong></p>\n'
            # 2. authors string
            partial_report += f'<p class="lorem">{authors_string}</em><br>\n'
            # 3. pubmed link
            article_id = str(article.pubmed_id).split("\n")[0]  # get pubmed id
            partial_report += f'<a href="https://pubmed.ncbi.nlm.nih.gov/{article_id}/">' \
                              f'https://pubmed.ncbi.nlm.nih.gov/{article_id}</a><br>\n'
            # 4. abstract
            partial_report += f'{article.abstract}</p>\n'
            partial_report += f'<hr class="lorem">\n'

        return partial_report, n_results

    def _pubmed_search_keywords(self, output_html_str: str):
        # init query with date
        query = f'(("{self.initial_date}"[Date - Create] : "3000"[Date - Create]))'
        # add keywords to the query
        query = self._pubmed_add_keywords_to_query(query)
        # make query
        results = self.pubmed_make_query(query)
        # get partial report from results
        partial_report, n_results = self._pubmed_get_partial_report_from_results(results)

        # update output
        output_html_str += f"<h1>General results " \
                           f"({n_results}) " \
                           f"({self.initial_date} - {datetime.now().strftime('%Y/%m/%d')})</h1>\n"
        output_html_str += partial_report

        return output_html_str

    def _pubmed_search_for_journal(self, output_html_str: str):
        # check number of journals
        if len(self.journals) == 0:
            logger.info("No Journals found")
        else:
            # iterate on journals
            for journal in self.journals:
                # init query with date and journal
                query = f'(("{self.initial_date}"[Date - Create] : "3000"[Date - Create])) AND ({journal}[Journal])'

                # get total of journal papers
                results = self.pubmed_make_query(query)
                n_tot_results = sum(1 for _ in results)
                if n_tot_results == self.max_results_for_query:
                    logger.warning(f"Number of paper published might exceed {self.max_results_for_query}. "
                                   f"Consider changing the max results for query using the flag "
                                   f"'--max_results_for_query'.")
                logger.info(f"Found total papers published on {journal}: {n_tot_results}")

                # if necessary, add keywords to the query
                if self.args.filter_journals:
                    query = self._pubmed_add_keywords_to_query(query)

                # run query for journal
                results = self.pubmed_make_query(query)

                # get partial report form results
                partial_report, n_results = self._pubmed_get_partial_report_from_results(results)

                # format n_results_str according to CLI
                if self.args.filter_journals:
                    n_results_str = f"({n_results}/{n_tot_results})"
                else:
                    n_results_str = f"({n_results})"

                # save result to html
                output_html_str += f"<h1>Results from {journal} " \
                                   f"{n_results_str} " \
                                   f"({self.initial_date} - {datetime.now().strftime('%Y/%m/%d')})</h1>\n"
                output_html_str += partial_report

        return output_html_str

    def _pubmed_search_for_authors(self, output_html_str: str):
        # check number of authors
        if len(self.authors) == 0:
            logger.info("No authors found.")

        # init authors query
        query = f'(("{self.initial_date}"[Date - Create] : "3000"[Date - Create]))'
        all_authors = " OR ".join([f"({author.replace(',', '')}[Author])" for author in self.authors])
        query = f"{query} AND ({all_authors})"

        # get tot results from authors
        results = self.pubmed_make_query(query)
        n_tot_results = sum(1 for _ in results)
        if n_tot_results == self.max_results_for_query:
            logger.warning(f"Number of paper published might exceed {self.max_results_for_query}. "
                           f"Consider changing the max results for query using the flag '--max_results_for_query'.")
        logger.info(f"Found total papers published for authors: {n_tot_results}")

        # if necessary, filter authors
        if self.args.filter_authors:
            query = self._pubmed_add_keywords_to_query(query)

        # make query
        results = self.pubmed_make_query(query)

        # get partial report from results
        partial_report, n_results = self._pubmed_get_partial_report_from_results(results)

        # adjust n_results_str according to user input
        if self.args.filter_journals:
            n_results_str = f"({n_results}/{n_tot_results})"
        else:
            n_results_str = f"({n_results})"

        # update output
        output_html_str += f"<h1>Results from Authors " \
                           f"{n_results_str} " \
                           f"({self.initial_date} - {datetime.now().strftime('%Y/%m/%d')})</h1>\n"
        output_html_str += partial_report

        return output_html_str

    def _gs_make_query(self, query):
        logger.info(f"Running Google Scholar query: {query}")
        query_params = {"q": query, **self.gs_parameters}  # get query parameters
        r = requests.get(self.gs_base_url, params=query_params)  # make query
        # return as json
        return r.json()

    def _gs_get_results_from_initial_date(self, results: Dict) -> List:
        organic_results = results["organic_results"]  # get organic results

        # get how many days ago the last paper on page was published
        last_result_days_ago = int(organic_results[-1]["snippet"][0])

        # if latest paper on page was published earlier than self.timedelta_days, go to next page;
        # else, get only the elements published earlier than self.timedelta_days days
        if last_result_days_ago <= self.timedelta_days:
            logger.info("Searching next GS page")
            r = requests.get(results["serpapi_pagination"]["next"])  # go to next page
            new_organic_results = self._gs_get_results_from_initial_date(r.json())
            return [*organic_results, *new_organic_results]
        else:
            output_list = [element for element in organic_results if int(element["snippet"][0]) < self.timedelta_days]
            return output_list

    def _gs_get_partial_reports_from_results(self, organic_results: List):
        partial_report = ""  # init partial report
        n_results = 0  # init n_results

        for element in organic_results:
            n_results += 1  # update n_results

            # generate 'authors string', i.e. a string containing the first author of the paper and any other
            # author in the list self.highlight authors
            article_authors = element["publication_info"]["authors"]  # get authors
            if len(article_authors) > 0:
                first_author = article_authors[0]
                first_author_name = first_author["name"]
                first_author_link = first_author["link"]
                authors_string = f'<a href="{first_author_link}">{first_author_name}</a> '
            else:
                authors_string = f"None "
            # finish author sting
            publication_date = datetime.now() - timedelta(days=element["snippet"][0])
            authors_string += f"et al. ({publication_date.strftime('%d/%m/%Y')})"

            # add publication info to partial report
            # 1. paper title
            paper_title = element["title"]
            partial_report += f'<p class="lorem" style="font-size: larger;"><strong>{paper_title}</strong></p>\n'
            # 2. authors string
            partial_report += f'<p class="lorem">{authors_string}</em><br>\n'
            # 3. Google Scholar Link
            paper_link = element["link"]
            partial_report += f'<a href="{paper_link}">{paper_link}</a><br>\n'
            # 4. snippet
            partial_report += f'{element["snippet"]}</p>\n'
            partial_report += f'<hr class="lorem">\n'

        return partial_report, n_results

    def _gs_search_for_keywords(self, output_html_str):
        query = "|".join([f"{keyword}" for keyword in self.keywords])  # build OR chained string
        query.replace("(", "")  # remove parenthesis
        query.replace(")", "")  # remove parenthesis
        query.replace(" AND ", " ")  # space correspond to AND in Google Scholar
        query.replace("AND", " ")
        query.replace(" OR ", "|")  # OR correspond to | in Google Scholar
        query.replace("OR", "|")
        query.replace("NOT ", "-")  # NOT correspond to - in Google Scholar

        # make query
        results = self._gs_make_query(query)

        # get results published from the initial date
        organic_results_from_initial_date = self._gs_get_results_from_initial_date(results)

    def run_pubmed_search(self):
        # init empty output_html_str
        output_html_str = ""

        # Generate the 'general' part using keywords
        if not self.args.suppress_general:
            output_html_str = self._pubmed_search_keywords(output_html_str)

        # Generate the journals part
        output_html_str = self._pubmed_search_for_journal(output_html_str)

        # search for authors
        output_html_str = self._pubmed_search_for_authors(output_html_str)

        # check if literature review is empty
        if output_html_str == "":
            logger.warning(f"LiRA output is empty.")

        # replace text in template
        with open("in/template.html", "r") as infile:
            template = infile.read()
        literature_review_report = template.replace("TO_REPLACE", output_html_str)

        # write report
        with open(OUT_HTML, "w") as html_file:
            logger.info("Saving HTML report... ")
            html_file.write(literature_review_report)
            logger.info("Done.")

    def run(self):
        # if args.last is true, check if OUT_HTML exists; else run_search
        if self.args.last:
            assert OUT_HTML.exists(), f"Last LiRA output not found. Should be in {OUT_HTML.resolve()}"
        else:
            self.run_pubmed_search()

        # open result in browser
        webbrowser.open(url=str(OUT_HTML.resolve()), new=0)


def main():
    lira = LiRA()
    lira.run()


if __name__ == "__main__":
    main()
