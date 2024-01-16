import json
import logging
import argparse
import webbrowser
from pathlib import Path
from typing import Dict, List
from datetime import datetime, timedelta
from itertools import product
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
OUT_JSON = OUT_FOLDER / Path("lira_output.json")


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
                       help="Date from which the Literature Review should start, "
                            "in format AAAA/MM/DD"
    )
    group.add_argument("--for-weeks", "-w",
                       type=int,
                       help="Number of weeks for the literature review. "
                            "LiRA will search for the n past weeks"
    )

    # add see last output
    group.add_argument("--last", "-L",
                       action='store_true',
                       help="Just opens the last LiRA output without running a search")

    # get option for configuration file
    parser.add_argument("--config", "-c",
                        type=str,
                        help="Define a configuration file to use instead of the "
                             "default config.json.")

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
                        help='Do not add to the output the Pubmed results obtained with '
                             'the keywords')

    # add '--max_results_for_query' to update the maximum number of results
    parser.add_argument("--max-results-for-query",
                        type=int,
                        help=f"Change the maximum number of results for each executed query. "
                             f"Default is {DEFAULT_PYMED_MAX_RESULTS}.\n"
                             f"Notice: the higher this value is, the higher will be the time to "
                             f"perform the search.")
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

    def article_dict(self,
                     authors: List[str],
                     title: str,
                     link: str,
                     abstract: str,
                     doi: str,
                     journal: str,
                     date: str) -> Dict:

        article_dict ={
                "authors": authors,
                "title": title,
                "link": link,
                "abstract": abstract,
                "doi": doi,
                "journal": journal,
                "date": date
            }
        
        return article_dict


class PubMedPipeline(EnginePipeline):
    """
    Pipeline for PubMed. Uses PyMed as backend.
    """
    def __init__(self, cli_args: argparse.Namespace):
        super().__init__(cli_args)

        # set name
        self.name = "pubmed"

        # load email
        self.email = self.config["email"]

        # init pymed
        self.pubmed = PubMed(tool="LiRA", email=self.email)

    def _add_keywords_to_query(self, query: str):
        keywords_query = " OR ".join([f"({keyword})" for keyword in self.keywords])
        query += f" AND ({keywords_query})"
        return query

    def make_query(self, query: str):
        logger.info(f"Running PubMed query (max res: {self.max_results_for_query}): {query}")

        results = self.pubmed.query(query, max_results=self.max_results_for_query)

        return results
    
    def _get_output_list_from_results(self, results, **kwargs):
        # init output list
        output_list = []

        # generate list of results
        for article in results:
            # get authors
            if len(article.authors) > 0:
                authors_list = [f"{a['lastname']}, {a['firstname']}" for a in article.authors]
            else:
                authors_list = [None]
            # get article_id
            article_id = str(article.pubmed_id).split("\n")[0]
            # get article doi
            article_doi = None if article.doi is None else article.doi.split('\n', maxsplit=1)[0]
            # generate dict
            article_dict = self.article_dict(
                authors=authors_list,
                title=article.title,
                link=f'https://pubmed.ncbi.nlm.nih.gov/{article_id}</a><br>',
                abstract=article.abstract,
                doi=article_doi,
                journal=article.journal if 'journal' not in kwargs else kwargs['journal'],
                date=article.publication_date.strftime(DATE_FORMAT)
            )
            # append to output list
            output_list.append(article_dict)

        # check number of results
        n_results = len(output_list)
        if n_results >= self.max_results_for_query:
            logger.warning(f"Number of paper published might exceed {self.max_results_for_query}. "
                           f"Consider changing the max results for query using the flag "
                           f"'--max_results_for_query'.")
        logger.info(f"Found {n_results} results")
            
        return output_list
    
    def search_for_keywords(self):
        # init query with date
        query = f'(("{self.initial_date}"[Date - Create] : "3000"[Date - Create]))'
        # add keywords to the query
        query = self._add_keywords_to_query(query)
        # make query
        results = self.make_query(query)
        return self._get_output_list_from_results(results)
    
    def search_for_journals(self):
        # init output list
        output_list = []

        # check number of journals
        if len(self.journals) == 0:
            logger.info("No Journals found")
        else:
            # iterate on journals
            for journal in self.journals:
                # init query with date and journal
                query = f'(("{self.initial_date}"[Date - Create] : "3000"[Date - Create])) AND ({journal}[Journal])'

                # if necessary, add keywords to the query
                if self.cli_args.filter_journals:
                    query = self._add_keywords_to_query(query)

                # run query for journal
                results = self.make_query(query)

                # get output list
                output_list.extend(self._get_output_list_from_results(results, journal=journal))
        
        return output_list

    def search_for_authors(self):
        # init output list
        output_list = []

        # check number of authors
        if len(self.authors) == 0:
            logger.info("No authors found.")
            return output_list
        else:
            # init authors query
            query = f'(("{self.initial_date}"[Date - Create] : "3000"[Date - Create]))'
            all_authors = " OR ".join([f"({author.replace(',', '')}[Author])" for author in self.authors])
            query = f"{query} AND ({all_authors})"

            # if necessary, filter authors
            if self.cli_args.filter_authors:
                query = self._add_keywords_to_query(query)

            # make query
            results = self.make_query(query)

            # append results to output list
            output_list.extend(self._get_output_list_from_results(results))

        return output_list

class GoogleScholarPipeline(EnginePipeline):
    """
    Pipeline for Google Scholar. Uses SerpAPI as backend.
    """
    def __init__(self, cli_args: argparse.Namespace):
        super().__init__(cli_args)
        # set name
        self.name = "google_scholar"

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

    def _get_days_ago_for_gs_organic_result(self, organic_result: Dict):
        """
        Given a Google Scholar organic result, return how many days ago it was published.

        :param organic_result: Google Scholar organic result as provided by SerpAPI
        :return:
        """
        snippet = organic_result["snippet"]
        days_ago = int(snippet.split(" days ago ")[0])
        return days_ago

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

        # check for error
        if "error" in full_results.keys():
            logger.info(f"SerpAPI Google Scholar returned the following error: {full_results['error']}")
            return {}

        # return as json
        return full_results

    def _get_results_from_initial_date(self, results: Dict) -> List:
        organic_results = results["organic_results"]  # get organic results

        # get how many days ago the last paper on page was published
        last_result_days_ago = self._get_days_ago_for_gs_organic_result(organic_results[-1])

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
                           if self._get_days_ago_for_gs_organic_result(ores) < self.timedelta_days]
            return output_list
  
    def _get_output_list_from_query(self, query):
        # init output list
        output_list = []

        # make query
        results = self.make_query(query)

        if results != {}:
            # get results published from the initial date
            organic_results_from_initial_date = self._get_results_from_initial_date(results)
          
            # create list of results
            for element in organic_results_from_initial_date:
                # get authors
                if "authors" in element["publication_info"]:
                    authors = [a["name"] for a in element["publication_info"]["authors"]]
                else:
                    authors = [None]
                # get date
                days_ago = timedelta(days=self._get_days_ago_for_gs_organic_result(element))
                publication_date = datetime.now() - days_ago
                # build dict for element
                element_dict = self.article_dict(
                    authors=authors,
                    title=element["title"],
                    link=element["link"],
                    abstract=element["snippet"],
                    doi=None,
                    journal=None,
                    date=publication_date.strftime(DATE_FORMAT)
                )
                # append to output list
                output_list.append(element_dict)

        return output_list
    
    def search_for_keywords(self):
        # init output list
        output_list = []
        # get query for keyword
        query = self._add_keywords_to_query("")
        # generate output_list
        output_list = self._get_output_list_from_query(query)
        return output_list

    def search_for_journals(self) -> List:
        # check number of journals
        if len(self.journals) == 0:
            logger.info("No Journals found")
            return []
        else:
            # iterate on journals
            query = "|".join([f"source:{j}" for j in self.journals])
            # if necessary, add keywords to the query
            if self.cli_args.filter_journals:
                query = self._add_keywords_to_query(query)
            # generate output list
            output_list = self._get_output_list_from_query(query)
            return output_list

    def search_for_authors(self) -> List:
        # check number of journals
        if len(self.authors) == 0:
            logger.info("No Authors found")
            return []
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
            # generate output list
            output_list = self._get_output_list_from_query(query)
            return output_list
       

class OutputGenerator:
    def __init__(self, results: List, cli_args: argparse.Namespace, config: Dict) -> None:
        # store results
        self.results = results
        # generate output folder
        OUT_FOLDER.mkdir(exist_ok=True)
        # get initial date
        if cli_args.from_date is None:
            initial_date = datetime.now() - timedelta(weeks=cli_args.for_weeks)
            self.initial_date = initial_date.strftime(DATE_FORMAT)
        else:
            self.initial_date = cli_args.from_date
        # config
        self.journals = config["journals"]
        self.authors = config["authors"]
        self.highlight_authors = config["highlight_authors"] + self.authors

    def to_json(self) -> None:
        with open(OUT_JSON, "w") as outfile:
            json.dump(self.results, outfile, indent=2)

    def __paper_dict_to_html(self, paper_dict: Dict) -> str:
        paper_html = ""  # init html

        # 1. add paper title
        paper_html += f'<p class="lorem" style="font-size: larger;"><strong>{paper_dict["title"]}</strong></p>\n'
        # 2. add author
        authors_string = f'{paper_dict["authors"][0]} et al. ({paper_dict["date"]})'
        if None not in paper_dict["authors"]:
            a_to_highlight = [a for a, ha in product(paper_dict["authors"], self.highlight_authors)
                            if (a.split(",")[0] in ha.split(",")) and (a.split(",")[1][1] in ha)]
            if a_to_highlight:
                a_to_highlight_str = "; ".join(a_to_highlight)
                a_to_highlight_str = f'\t <span style="color: #ff0000">Notice: {a_to_highlight_str} in authors</span>'
                authors_string += a_to_highlight_str
        paper_html += f'<p class="lorem">{authors_string}</em><br>\n'
        # 3. add link
        paper_html += f'<a href="{paper_dict["link"]}"> {paper_dict["link"]}</a><br>\n'
        # 4. add abstract
        paper_html += f'{paper_dict["abstract"]}</p>\n'
        paper_html += '<hr class="lorem">\n'

        return paper_html

    def to_html(self) -> None:
        # init output html
        output_html_str = ""
        
        # for each engine results
        for engine_dict in self.results:
            engine_name = engine_dict['engine']
            if engine_name == "pubmed":
                sections = ["general", "authors"]
            else:
                sections = ["general", "journals", "authors"]

            for section in sections:
                # generate results part for section
                n_results = len(engine_dict['results'][section])
                output_html_str += f"<h1>{section.capitalize()} results [{engine_dict['engine']}]" \
                                f"({n_results}) " \
                                f"({self.initial_date} - {datetime.now().strftime(DATE_FORMAT)})</h1>\n"
                for paper_dict in engine_dict['results'][section]:
                    output_html_str += self.__paper_dict_to_html(paper_dict)
            
            if (engine_name == "pubmed"):
                for j in self.journals:
                    results_for_j = [article for article in engine_dict['results']['journals'] if article['journal'] == j]
                    n_results_for_j = len(results_for_j)
                    output_html_str += f"<h1>{j.capitalize()} results [{engine_dict['engine']}]" \
                                    f"({n_results_for_j}) " \
                                    f"({self.initial_date} - {datetime.now().strftime(DATE_FORMAT)})</h1>\n"
                    for paper_dict in results_for_j:
                        output_html_str += self.__paper_dict_to_html(paper_dict)
                
        # replace text in template
        with open("in/template.html", "r") as infile:
            template = infile.read()
        literature_review_report = template.replace("TO_REPLACE", output_html_str)

        # write report
        with open(OUT_HTML, "w") as html_file:
            logger.info("Saving HTML report... ")
            html_file.write(literature_review_report)
            logger.info("Done.") 


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

    # init list of papers
    output_list = []

    for engine in engines_list:
        # Generate the 'general' part using keywords
        if not args.suppress_general:
            general_list = engine.search_for_keywords()
        else:
            general_list = []
        # Generate the journals part
        journal_list = engine.search_for_journals()
        # Generate the authors part
        authors_list = engine.search_for_authors()
        # generate dict for engine
        d = {
            "engine": engine.name,
            "results": {
                "general": general_list,
                "journals": journal_list,
                "authors": authors_list
            }
        }
        # append to output list
        output_list.append(d)
        

    # check if literature review is empty
    if len(output_list) == 0:
        logger.warning(f"LiRA output is empty.")

    # get output generator
    og = OutputGenerator(output_list, cli_args=args, config=config)

    # generate json
    og.to_json()

    # generate html
    og.to_html()

def main():
    # generate folders
    CONFIG_FOLDER.mkdir(exist_ok=True)  # generate config folder

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
