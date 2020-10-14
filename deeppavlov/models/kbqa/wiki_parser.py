# Copyright 2017 Neural Networks and Deep Learning lab, MIPT
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import datetime
import re
from logging import getLogger
from typing import List, Tuple, Dict, Union
from collections import namedtuple

from hdt import HDTDocument

from deeppavlov.core.common.file import load_pickle
from deeppavlov.core.commands.utils import expand_path
from deeppavlov.core.common.registry import register
from deeppavlov.core.models.component import Component

log = getLogger(__name__)

@register('wikidata')
class Wikidata:
    def __init__(self, wiki_filename: str, file_format: str = "hdt", **kwargs) -> None:
        wiki_path = expand_path(wiki_filename)
        self.file_format = file_format
        if self.file_format == "hdt":
            self.document = HDTDocument(str(wiki_path))
        elif self.file_format == "pickle":
            self.document = load_pickle(wiki_path)
        else:
            raise ValueError("Unsupported file format")
    
    def __call__(self, queries: List[Union[str, List[str]]]):
        print("queries", queries)
        triplets = []
        for query in queries:
            print("query", query)
            if self.file_format == "hdt":
                tr, c = self.document.search_triples(*query)
            if self.file_format == "pickle":
                tr = self.document.get(query, {})
            triplets.append(tr)
        print("triplets", triplets)
        return triplets

@register('wiki_parser')
class WikiParser:
    """This class extract relations, objects or triplets from Wikidata HDT file"""

    def __init__(self, wikidata: Wikidata, file_format: str = "hdt", lang: str = "@en", **kwargs) -> None:
        """

        Args:
            wikidata: class deeppavlov.models.kbqa.wiki_parser:Wikidata
            file_format: format of Wikidata file
            lang: Russian or English language
            **kwargs:
        """
        self.description_rel = "http://schema.org/description"
        self.file_format = file_format
        self.wikidata = wikidata
        self.lang = lang

    def __call__(self, what_return: List[str],
                 query_seq: List[List[str]],
                 filter_info: List[Tuple[str]] = None,
                 order_info: namedtuple = None) -> List[List[str]]:
        """
            Let us consider an example of the question "What is the deepest lake in Russia?"
            with the corresponding SPARQL query            
            "SELECT ?ent WHERE { ?ent wdt:P31 wd:T1 . ?ent wdt:R1 ?obj . ?ent wdt:R2 wd:E1 } ORDER BY ASC(?obj) LIMIT 5"

            arguments:
                what_return: ["?obj"]
                query_seq: [["?ent", "http://www.wikidata.org/prop/direct/P17", "http://www.wikidata.org/entity/Q159"]
                            ["?ent", "http://www.wikidata.org/prop/direct/P31", "http://www.wikidata.org/entity/Q23397"],
                            ["?ent", "http://www.wikidata.org/prop/direct/P4511", "?obj"]]
                filter_info: []
                order_info: order_info(variable='?obj', sorting_order='asc')
        """
        extended_combs = []
        combs = []
        if "qualifier" not in filter_info:
            for n, query in enumerate(query_seq):
                unknown_elem_positions = [(pos, elem) for pos, elem in enumerate(query) if elem.startswith('?')]
                """
                    n = 0, query = ["?ent", "http://www.wikidata.org/prop/direct/P17", "http://www.wikidata.org/entity/Q159"]
                           unknown_elem_positions = ["?ent"]
                    n = 1, query = ["?ent", "http://www.wikidata.org/prop/direct/P31", "http://www.wikidata.org/entity/Q23397"]
                           unknown_elem_positions = [(0, "?ent")]
                    n = 2, query = ["?ent", "http://www.wikidata.org/prop/direct/P4511", "?obj"]
                           unknown_elem_positions = [(0, "?ent"), (2, "?obj")]
                """
                if n == 0:
                    combs = self.search(query, unknown_elem_positions)
                    # combs = [{"?ent": "http://www.wikidata.org/entity/Q5513"}, ...]
                else:
                    if combs:
                        known_elements = []
                        extended_combs = []
                        for elem in query:
                            if elem in combs[0].keys():
                                known_elements.append(elem)
                        for comb in combs:
                            """
                                n = 1
                                query = ["?ent", "http://www.wikidata.org/prop/direct/P31", "http://www.wikidata.org/entity/Q23397"]
                                comb = {"?ent": "http://www.wikidata.org/entity/Q5513"}
                                known_elements = ["?ent"], known_values = ["http://www.wikidata.org/entity/Q5513"]
                                filled_query = ["http://www.wikidata.org/entity/Q5513", 
                                                "http://www.wikidata.org/prop/direct/P31", 
                                                "http://www.wikidata.org/entity/Q23397"]
                                new_combs = [["http://www.wikidata.org/entity/Q5513", 
                                              "http://www.wikidata.org/prop/direct/P31", 
                                              "http://www.wikidata.org/entity/Q23397"], ...]
                                extended_combs = [{"?ent": "http://www.wikidata.org/entity/Q5513"}, ...]
                            """                        
                            known_values = [comb[known_elem] for known_elem in known_elements]
                            for known_elem, known_value in zip(known_elements, known_values):
                                filled_query = [elem.replace(known_elem, known_value) for elem in query]
                                new_combs = self.search(filled_query, unknown_elem_positions)
                                for new_comb in new_combs:
                                    extended_combs.append({**comb, **new_comb})
                    combs = extended_combs

        if combs:
            if filter_info:
                for filter_elem, filter_value in filter_info:
                    combs = [comb for comb in combs if filter_value in comb[filter_elem]]

            if order_info and order_info.variable is not None:
                reverse = True if order_info.sorting_order == "desc" else False
                sort_elem = order_info.variable
                combs = sorted(combs, key=lambda x: float(x[sort_elem].split('^^')[0].strip('"')), reverse=reverse)
                combs = [combs[0]]

            if what_return[-1].startswith("count"):
                combs = [[combs[0][key] for key in what_return[:-1]] + [len(combs)]]
            else:
                combs = [[elem[key] for key in what_return] for elem in combs]

        return combs

    def search(self, query: List[str], unknown_elem_positions: List[Tuple[int, str]]) -> List[Dict[str, str]]:
        query = list(map(lambda elem: "" if elem.startswith('?') else elem, query))
        subj, rel, obj = query
        if self.file_format == "hdt":
            triplets = self.wikidata([query])[0]
            if rel == self.description_rel:
                triplets = [triplet for triplet in triplets if triplet[2].endswith(self.lang)]
            combs = [{elem: triplet[pos] for pos, elem in unknown_elem_positions} for triplet in triplets]
        else:
            if subj:
                direction = "forw"
            if obj:
                direction = "backw"
            subj = subj.split('/')[-1]
            triplets = self.wikidata([subj])[0].get(direction, [])
            triplets = [[subj, triplet[0], obj] for triplet in triplets for obj in triplet[1:]]
            if rel:
                rel = rel.split('/')[-1]
                triplets = [triplet for triplet in triplets if triplet[1] == rel]
            combs = [{elem: triplet[pos] for pos, elem in unknown_elem_positions} for triplet in triplets]
        return combs

    def find_label(self, entity: str, question: str) -> str:
        entity = str(entity).replace('"', '')
        if self.file_format == "hdt":
            if entity.startswith("Q"):
                # example: "Q5513"
                entity = "http://www.wikidata.org/entity/" + entity
                # "http://www.wikidata.org/entity/Q5513"

            if entity.startswith("http://www.wikidata.org/entity/"):
                labels = self.wikidata([[entity, "http://www.w3.org/2000/01/rdf-schema#label", ""]])[0]
                # labels = [["http://www.wikidata.org/entity/Q5513", "http://www.w3.org/2000/01/rdf-schema#label", '"Lake Baikal"@en'], ...]
                for label in labels:
                    if label[2].endswith(self.lang):
                        found_label = label[2].strip(self.lang).replace('"', '')
                        return found_label

            elif entity.endswith(self.lang):
                # entity: '"Lake Baikal"@en'
                entity = entity[:-3]
                return entity

            elif "^^" in entity:
                """
                    examples:
                        '"1799-06-06T00:00:00Z"^^<http://www.w3.org/2001/XMLSchema#dateTime>' (date)
                        '"+1642"^^<http://www.w3.org/2001/XMLSchema#decimal>' (number)
                """
                entity = entity.split("^^")[0]
                for token in ["T00:00:00Z", "+"]:
                    entity = entity.replace(token, '')
                year = re.findall("([\d]{3,4})-[\d]{1,2}-[\d]{1,2}", entity)
                if "how old" in question.lower() and year:
                    entity = datetime.datetime.now().year - int(year[0])
                return entity

            elif entity.isdigit():
                return entity
        if self.file_format == "pickle":
            if entity:
                if entity.startswith("Q"):
                    triplets = self.wikidata([entity])[0].get("forw", [])
                    for triplet in triplets:
                        if triplet[0] == "name_en":
                            return triplet[1]
                else:
                    return entity

        return "Not Found"

    def find_alias(self, entity: str) -> List[str]:
        aliases = []
        if entity.startswith("http://www.wikidata.org/entity/"):
            labels, cardinality = self.document.search_triples(entity,
                                                               "http://www.w3.org/2004/02/skos/core#altLabel", "")
            aliases = [label[2].strip(self.lang).strip('"') for label in labels if label[2].endswith(self.lang)]
        return aliases

    def find_rels(self, entity: str, direction: str, rel_type: str = "no_type") -> List[str]:
        if self.file_format == "hdt":
            if direction == "forw":
                query = [f"http://www.wikidata.org/entity/{entity}", "", ""]
            else:
                query = ["", "", f"http://www.wikidata.org/entity/{entity}"]
            triplets = self.wikidata([query])[0]

            if rel_type != "no_type":
                start_str = f"http://www.wikidata.org/prop/{rel_type}"
            else:
                start_str = "http://www.wikidata.org/prop/P"
            rels = [triplet[1] for triplet in triplets if triplet[1].startswith(start_str)]
        if self.file_format == "pickle":
            triplets = self.wikidata([entity])[0].get(direction, [])
            rels = [triplet[0] for triplet in triplets]
        return rels
