import json
from pymed import PubMed

# load keywords
with open("keywords.json", "r") as infile:
    keywords = json.load(infile)

# get authors
authors = keywords["authors"]
my_authors = keywords["my_authors"]
authors += my_authors

# init pubmed
pubmed = PubMed(tool="LiRA", email="franco.pradelli94@gmail.com")  # init pubmed

for author in authors:
    # get the first paper
    article, = list(pubmed.query(query=author, max_results=1))
    # get the author of interest
    author_dict = list(filter(lambda a: a['lastname'] in author, article.authors))
    print(author_dict)
