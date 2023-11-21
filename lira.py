import json
import logging
import argparse
import webbrowser
from pathlib import Path
from typing import Dict, List, Tuple
from datetime import datetime, timedelta
import requests
from pymed import PubMed

# Initialize logger
logger = logging.getLogger(__name__)
handler = logging.StreamHandler()
handler.setLevel(logging.DEBUG)
formatter = logging.Formatter("%(levelname)s:%(name)s: %(message)s")
handler.setFormatter(formatter)
logger.addHandler(handler)

# Macros definition
CONFIG_FOLDER = Path("config")
DEFAULT_CONFIG_FILE = CONFIG_FOLDER / Path("config.json")
OUT_FOLDER = Path("out")
OUT_HTML = OUT_FOLDER / Path("lira_output.html")
DEFAULT_PYMED_MAX_RESULTS = 500
DATE_FORMAT = "%Y/%m/%d"


def parse_cli_args() -> argparse.Namespace:
    """
    Parse CLI arguments

    :return: CLI arguments as namespace
    """
    # init parser
    parser = argparse.ArgumentParser(description="LiRA: Literature Review Automated. "
                                                 "Based on pymed to query PubMed programmatically.")

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


def get_days_ago_for_gs_organic_result(organic_result: Dict):
    """
    Given a Google Scholar organic result, return how many days ago it was published.

    :param organic_result: Google Scholar organic result as provided by SerpAPI
    :return:
    """
    snippet = organic_result["snippet"]
    days_ago = int(snippet.split(" days ago ")[0])
    return days_ago


class EnginePipeline:
    def __init__(self, cli_args: argparse.Namespace):
        # save args
        self.cli_args = cli_args

        # get max results for search
        if cli_args.max_results_for_query is None:
            self.max_results_for_query = DEFAULT_PYMED_MAX_RESULTS
        else:
            self.max_results_for_query = cli_args.max_results_for_query

        # get initial date
        if cli_args.from_date is None:
            initial_date = datetime.now() - timedelta(weeks=cli_args.for_weeks)
            self.initial_date = initial_date.strftime(DATE_FORMAT)
        else:
            self.initial_date = cli_args.from_date

        # read config
        self.config = read_config(cli_args)

        # get common propreties
        self.keywords = self.config["keywords"]
        self.journals = self.config["journals"]
        self.authors = self.config["authors"]
        self.highlight_authors = self.config["highlight_authors"] + self.authors


class PubMedPipeline(EnginePipeline):
    """
    Pipeline for PubMed. Uses PyMed as backend.
    """
    def __init__(self, cli_args: argparse.Namespace):
        super().__init__(cli_args)

        # load email
        self.email = self.config["email"]

        # init pymed
        self.pubmed = PubMed(tool="LiRA", email=self.email)

    def _get_authors_to_highlight_from_list(self, list_of_authors: List):
        authors_to_highlight = list(filter(
            lambda a: any([(str(a['lastname']) in ha) and (str(a['firstname']) in ha)
                           for ha in self.highlight_authors]),
            list_of_authors
        ))
        return authors_to_highlight

    def _add_keywords_to_query(self, query: str):
        keywords_query = " OR ".join([f"({keyword})" for keyword in self.keywords])
        query += f" AND ({keywords_query})"
        return query

    def make_query(self, query: str):
        logger.info(f"Running PubMed query (max res: {self.max_results_for_query}): {query}")
        results = self.pubmed.query(query, max_results=self.max_results_for_query)

        return results

    def _get_partial_report_from_results(self, results):
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
            partial_report += '<hr class="lorem">\n'

        return partial_report, n_results

    def search_for_keywords(self, output_html_str: str):
        # init query with date
        query = f'(("{self.initial_date}"[Date - Create] : "3000"[Date - Create]))'
        # add keywords to the query
        query = self._add_keywords_to_query(query)
        # make query
        results = self.make_query(query)
        # get partial report from results
        partial_report, n_results = self._get_partial_report_from_results(results)

        # update output
        output_html_str += f"<h1>General results [PubMed]" \
                           f"({n_results}) " \
                           f"({self.initial_date} - {datetime.now().strftime('%Y/%m/%d')})</h1>\n"
        output_html_str += partial_report

        return output_html_str

    def search_for_journal(self, output_html_str: str):
        # check number of journals
        if len(self.journals) == 0:
            logger.info("No Journals found")
        else:
            # iterate on journals
            for journal in self.journals:
                # init query with date and journal
                query = f'(("{self.initial_date}"[Date - Create] : "3000"[Date - Create])) AND ({journal}[Journal])'

                # get total of journal papers
                results = self.make_query(query)
                n_tot_results = sum(1 for _ in results)
                if n_tot_results == self.max_results_for_query:
                    logger.warning(f"Number of paper published might exceed {self.max_results_for_query}. "
                                   f"Consider changing the max results for query using the flag "
                                   f"'--max_results_for_query'.")
                logger.info(f"Found total papers published on {journal}: {n_tot_results}")

                # if necessary, add keywords to the query
                if self.cli_args.filter_journals:
                    query = self._add_keywords_to_query(query)

                # run query for journal
                results = self.make_query(query)

                # get partial report form results
                partial_report, n_results = self._get_partial_report_from_results(results)

                # format n_results_str according to CLI
                if self.cli_args.filter_journals:
                    n_results_str = f"({n_results}/{n_tot_results})"
                else:
                    n_results_str = f"({n_results})"

                # save result to html
                output_html_str += f"<h1>Results from {journal} " \
                                   f"{n_results_str} " \
                                   f"({self.initial_date} - {datetime.now().strftime('%Y/%m/%d')})</h1>\n"
                output_html_str += partial_report

        return output_html_str

    def search_for_authors(self, output_html_str: str):
        # check number of authors
        if len(self.authors) == 0:
            logger.info("No authors found.")
        else:
            # init authors query
            query = f'(("{self.initial_date}"[Date - Create] : "3000"[Date - Create]))'
            all_authors = " OR ".join([f"({author.replace(',', '')}[Author])" for author in self.authors])
            query = f"{query} AND ({all_authors})"

            # get tot results from authors
            results = self.make_query(query)
            n_tot_results = sum(1 for _ in results)
            if n_tot_results == self.max_results_for_query:
                logger.warning(f"Number of paper published might exceed {self.max_results_for_query}. "
                               f"Consider changing the max results for query using the flag '--max_results_for_query'.")
            logger.info(f"Found total papers published for authors: {n_tot_results}")

            # if necessary, filter authors
            if self.cli_args.filter_authors:
                query = self._add_keywords_to_query(query)

            # make query
            results = self.make_query(query)

            # get partial report from results
            partial_report, n_results = self._get_partial_report_from_results(results)

            # adjust n_results_str according to user input
            if self.cli_args.filter_journals:
                n_results_str = f"({n_results}/{n_tot_results})"
            else:
                n_results_str = f"({n_results})"

            # update output
            output_html_str += f"<h1>Results from Authors " \
                               f"{n_results_str} " \
                               f"({self.initial_date} - {datetime.now().strftime('%Y/%m/%d')})</h1>\n"
            output_html_str += partial_report

        return output_html_str


class GoogleScholarPipeline(EnginePipeline):
    """
    Pipeline for Google Scholar. Uses SerpAPI as backend.
    """
    def __init__(self, cli_args: argparse.Namespace):
        super().__init__(cli_args)

        # get time delta between now and initial date
        time_range: timedelta = datetime.now() - datetime.strptime(self.initial_date, DATE_FORMAT)
        self.timedelta_days = time_range.days

        # get serpapi key
        self.serpapi_key = self.config["serpapi_key"]

        # create base url for google scholar
        self.gs_base_url = "https://serpapi.com/search?engine=google_scholar"

        # init base request parameters for google scholar
        self.gs_parameters = {
            "api_key": self.serpapi_key,
            "scisbd": 1,  # get results from most recent
            "num": self.max_results_for_query
        }

    def _add_keywords_to_query(self, query: str):
        keyword_query = "|".join([f"{keyword}" for keyword in self.keywords])  # build OR chained string
        keyword_query = keyword_query.replace("(", "")  # remove parenthesis
        keyword_query = keyword_query.replace(")", "")  # remove parenthesis
        keyword_query = keyword_query.replace(" AND ", " ")  # space correspond to AND in Google Scholar
        keyword_query = keyword_query.replace("AND", " ")
        keyword_query = keyword_query.replace(" OR ", "|")  # OR correspond to | in Google Scholar
        keyword_query = keyword_query.replace("OR", "|")
        keyword_query = keyword_query.replace("NOT ", "-")  # NOT correspond to - in Google Scholar

        if len(query) == 0:
            return keyword_query
        else:
            return f"{query} {keyword_query}"

    def make_query(self, query):
        # divide the query in chunks
        len_query = len(query)
        query_frame = [0, 0]
        frame_length = 255
        query_list = []
        for i, char in enumerate(query):
            if char == '|':
                query_frame[1] = i
            if ((i % frame_length) == 0) and (i != 0):
                query_list.append(query[query_frame[0]:query_frame[1]])
                query_frame[0] = query_frame[1] + 1
            if i == len_query - 1:
                query_list.append(query[query_frame[0]:len_query])

        # run each query
        full_results = {}
        logging.debug(f"Built query list: {query_list}")
        for q in query_list:
            logger.info(f"Running Google Scholar query: {q}")
            query_params = {"q": q, **self.gs_parameters}  # get query parameters
            r = requests.get(self.gs_base_url, params=query_params)  # make query
            full_results.update(r.json())
        # return as json
        return full_results

    def _get_results_from_initial_date(self, results: Dict) -> List:
        organic_results = results["organic_results"]  # get organic results

        # get how many days ago the last paper on page was published
        last_result_days_ago = get_days_ago_for_gs_organic_result(organic_results[-1])

        # if latest paper on page was published earlier than self.timedelta_days, go to next page;
        # else, get only the elements published earlier than self.timedelta_days days
        if last_result_days_ago <= self.timedelta_days:
            logger.info("Searching next GS page")
            r = requests.get(results["serpapi_pagination"]["next"], params={"api_key": self.serpapi_key})  # next page
            next_results = r.json()
            new_organic_results = self._get_results_from_initial_date(next_results)
            return [*organic_results, *new_organic_results]
        else:
            output_list = [ores for ores in organic_results
                           if get_days_ago_for_gs_organic_result(ores) < self.timedelta_days]
            return output_list

    def _get_partial_reports_from_results(self, organic_results: List) -> Tuple[str, int]:
        partial_report = ""  # init partial report
        n_results = 0  # init n_results

        for element in organic_results:
            n_results += 1  # update n_results

            # generate 'authors string', i.e. a string containing the first author of the paper and any other
            # author in the list self.highlight authors
            if "authors" in element["publication_info"]:
                article_authors = element["publication_info"]["authors"]  # get authors
                if len(article_authors) > 0:
                    first_author = article_authors[0]
                    first_author_name = first_author["name"]
                    first_author_link = first_author["link"]
                    authors_string = f'<a href="{first_author_link}">{first_author_name}</a> '
                else:
                    authors_string = f"None "
            else:
                authors_string = f"None "

            # finish author sting
            publication_date = datetime.now() - timedelta(days=get_days_ago_for_gs_organic_result(element))
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

    def _generate_partial_report_from_query(self, query: str, partial_report_header: str) -> str:
        # make query
        results = self.make_query(query)
        # get results published from the initial date
        organic_results_from_initial_date = self._get_results_from_initial_date(results)
        # get partial reports from results
        partial_report, n_results = self._get_partial_reports_from_results(organic_results_from_initial_date)
        # update output
        output_report = f"<h1>{partial_report_header} [Google Scholar]" \
                        f"({n_results}) " \
                        f"({self.initial_date} - {datetime.now().strftime('%Y/%m/%d')})</h1>\n"
        output_report += partial_report

        return output_report

    def search_for_keywords(self, output_html_str: str) -> str:
        # get query for keyword
        query = self._add_keywords_to_query("")
        # update output_html_report
        output_html_str += self._generate_partial_report_from_query(query=query,
                                                                    partial_report_header="General results")
        return output_html_str

    def search_for_journal(self, output_html_str: str) -> str:
        # check number of journals
        if len(self.journals) == 0:
            logger.info("No Journals found")
        else:
            # iterate on journals
            query = "|".join([f"source:{j}" for j in self.journals])
            # if necessary, add keywords to the query
            if self.cli_args.filter_journals:
                query = self._add_keywords_to_query(query)
            # update output_html_str
            output_html_str += self._generate_partial_report_from_query(query=query,
                                                                        partial_report_header="Results from Journals")
        return output_html_str

    def search_for_authors(self, output_html_str: str) -> str:
        # check number of journals
        if len(self.authors) == 0:
            logger.info("No Authors found")
        else:
            # build the authors list in the format required by GS
            gs_authors_list = []
            for a in self.authors:
                a_familiy_name:str  = a.split(',')[0]
                a_given_name: str = a.split(',')[1]
                if a_given_name.isupper():
                    a_initials = a_given_name
                else:
                    a_initials = a_given_name.replace(' ', '')[0]
                gs_authors_list.append(f"{a_familiy_name} {a_initials}")
            # generate the query
            query = "|".join([f"author:{a}" for a in gs_authors_list])
            # if necessary, add keywords to the query
            if self.cli_args.filter_authors:
                query = self._add_keywords_to_query(query)
            # update output_html_str
            output_html_str += self._generate_partial_report_from_query(query=query,
                                                                        partial_report_header="Results from Authors")

        return output_html_str


def run_search(args):
    # read config
    config = read_config(args)

    # init engines
    engines_list: List[EnginePipeline] = []
    if "engine" in config.keys():
        if "pubmed" in config["engine"]:
            engines_list.append(PubMedPipeline(args))
        if "google-scholar" in config["engine"]:
            engines_list.append(GoogleScholarPipeline(args))
    else:
        engines_list.append(PubMedPipeline(args))
        engines_list.append(GoogleScholarPipeline(args))

    # init empty output_html_str
    output_html_str = ""

    for engine in engines_list:
        # Generate the 'general' part using keywords
        if not args.suppress_general:
            output_html_str = engine.search_for_keywords(output_html_str)
        # Generate the journals part
        output_html_str = engine.search_for_journal(output_html_str)
        # Generate the authors part
        output_html_str = engine.search_for_authors(output_html_str)

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


def main():
    # generate folders
    CONFIG_FOLDER.mkdir(exist_ok=True)  # generate config folder
    OUT_FOLDER.mkdir(exist_ok=True)  # generate out folder

    # check if config file exists
    assert DEFAULT_CONFIG_FILE.exists(), f"Configuration file not found. To work with LiRA, create a default " \
                                         f"configuration file config/config.json."

    # parse CLI arguments
    args = parse_cli_args()

    # manage log
    log_level = logging.WARNING if args.quiet else logging.INFO
    logger.setLevel(log_level)
    
    # if args.last is true, check if OUT_HTML exists; else run_search
    if args.last:
        assert OUT_HTML.exists(), f"Last LiRA output not found. Should be in {OUT_HTML.resolve()}"
    else:
        run_search(args)

    # open result in browser
    webbrowser.open(url=str(OUT_HTML.resolve()), new=0)


if __name__ == "__main__":
    main()
