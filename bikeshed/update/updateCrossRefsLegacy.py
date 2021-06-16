import json
import os
import re
from collections import defaultdict

import certifi
import tenacity
from json_home_client import Client as APIClient

from .. import config
from ..messages import *

# Leftover code just for extracting headings from Shepherd,
# since Reffy's heading code is currently broken for multipage specs.
# TODO: Get Reffy's data from single-page specs,
# and only use this for the handful of remaining multipage specs
# Shepherd knows about.

def legacyFetchHeadings():
    say("Downloading anchor data...")
    shepherd = APIClient(
        "https://api.csswg.org/shepherd/",
        version="vnd.csswg.shepherd.v1",
        ca_cert_path=certifi.where(),
    )
    rawSpecData = dataFromApi(shepherd, "specifications", draft=True)
    if not rawSpecData:
        return

    specs = dict()
    headings = defaultdict(dict)
    for i, rawSpec in enumerate(rawSpecData.values(), 1):
        rawSpec = dataFromApi(
            shepherd, "specifications", draft=True, anchors=True, spec=rawSpec["name"]
        )
        spec = genSpec(rawSpec)
        specs[spec["vshortname"]] = spec
        specHeadings = headings[spec["vshortname"]]

        def setStatus(obj, status):
            obj["status"] = status
            return obj

        rawAnchorData = [
            setStatus(x, "snapshot")
            for x in linearizeAnchorTree(rawSpec.get("anchors", []))
        ] + [
            setStatus(x, "current")
            for x in linearizeAnchorTree(rawSpec.get("draft_anchors", []))
        ]
        for rawAnchor in rawAnchorData:
            if "section" in rawAnchor and rawAnchor["section"] is True:
                addToHeadings(fixupAnchor(rawAnchor), specHeadings, spec=spec)

    cleanSpecHeadings(headings)
    return headings


@tenacity.retry(
    reraise=True, stop=tenacity.stop_after_attempt(3), wait=tenacity.wait_random(1, 2)
)
def dataFromApi(api, *args, **kwargs):
    anchorDataContentTypes = [
        "application/json",
        "application/vnd.csswg.shepherd.v1+json",
    ]
    res = api.get(*args, **kwargs)
    if not res:
        raise Exception(
            "Unknown error fetching anchor data. This might be transient; try again in a few minutes, and if it's still broken, please report it on GitHub."
        )
    data = res.data
    if res.status_code == 406:
        raise Exception(
            "This version of the anchor-data API is no longer supported. Try updating Bikeshed. If the error persists, please report it on GitHub."
        )
    if res.content_type not in anchorDataContentTypes:
        raise Exception(f"Unrecognized anchor-data content-type '{res.contentType}'.")
    if res.status_code >= 300:
        raise Exception(
            f"Unknown error fetching anchor data; got status {res.status_code} and bytes:\n{data.decode('utf-8')}"
        )
    if isinstance(data, bytes):
        raise Exception(f"Didn't get expected JSON data. Got:\n{data.decode('utf-8')}")
    return data


def linearizeAnchorTree(multiTree, list=None):
    if list is None:
        list = []
    # Call with multiTree being a list of trees
    for item in multiTree:
        if item["type"] in config.dfnTypes.union(["dfn", "heading"]):
            list.append(item)
        if item.get("children"):
            linearizeAnchorTree(item["children"], list)
            del item["children"]
    return list


def genSpec(rawSpec):
    spec = {
        "vshortname": rawSpec["name"],
        "shortname": rawSpec.get("short_name"),
        "snapshot_url": rawSpec.get("base_uri"),
        "current_url": rawSpec.get("draft_uri"),
        "title": rawSpec.get("title"),
        "description": rawSpec.get("description"),
        "work_status": rawSpec.get("work_status"),
        "working_group": rawSpec.get("working_group"),
        "domain": rawSpec.get("domain"),
        "status": rawSpec.get("status"),
        "abstract": rawSpec.get("abstract"),
    }
    if spec["shortname"] is not None and spec["vshortname"].startswith(
        spec["shortname"]
    ):
        # S = "foo", V = "foo-3"
        # Strip the prefix
        level = spec["vshortname"][len(spec["shortname"]) :]
        if level.startswith("-"):
            level = level[1:]
        if level.isdigit():
            spec["level"] = int(level)
        else:
            spec["level"] = 1
    elif spec["shortname"] is None and re.match(r"(.*)-(\d+)", spec["vshortname"]):
        # S = None, V = "foo-3"
        match = re.match(r"(.*)-(\d+)", spec["vshortname"])
        spec["shortname"] = match.group(1)
        spec["level"] = int(match.group(2))
    else:
        spec["shortname"] = spec["vshortname"]
        spec["level"] = 1
    return spec


def fixupAnchor(anchor):
    """Miscellaneous fixes to the anchors before I start processing"""

    # Normalize whitespace to a single space
    for k, v in list(anchor.items()):
        if isinstance(v, str):
            anchor[k] = re.sub(r"\s+", " ", v.strip())
        elif isinstance(v, list):
            for k1, v1 in enumerate(v):
                if isinstance(v1, str):
                    anchor[k][k1] = re.sub(r"\s+", " ", v1.strip())
    return anchor


def addToHeadings(rawAnchor, specHeadings, spec):
    uri = rawAnchor["uri"]
    if uri[0] == "#":
        # Either single-page spec, or link on the top page of a multi-page spec
        heading = {
            "url": spec["{}_url".format(rawAnchor["status"])] + uri,
            "number": rawAnchor["name"]
            if re.match(r"[\d.]+$", rawAnchor["name"])
            else "",
            "text": rawAnchor["title"],
            "spec": spec["title"],
        }
        fragment = uri
        shorthand = "/" + fragment
    else:
        # Multi-page spec, need to guard against colliding IDs
        if "#" in uri:
            # url to a heading in the page, like "foo.html#bar"
            match = re.match(r"([\w-]+).*?(#.*)", uri)
            if not match:
                die(
                    "Unexpected URI pattern '{0}' for spec '{1}'. Please report this to the Bikeshed maintainer.",
                    uri,
                    spec["vshortname"],
                )
                return
            page, fragment = match.groups()
            page = "/" + page
        else:
            # url to a page itself, like "foo.html"
            page, _, _ = uri.partition(".")
            page = "/" + page
            fragment = "#"
        shorthand = page + fragment
        heading = {
            "url": spec["{}_url".format(rawAnchor["status"])] + uri,
            "number": rawAnchor["name"]
            if re.match(r"[\d.]+$", rawAnchor["name"])
            else "",
            "text": rawAnchor["title"],
            "spec": spec["title"],
        }
    if shorthand not in specHeadings:
        specHeadings[shorthand] = {}
    specHeadings[shorthand][rawAnchor["status"]] = heading
    if fragment not in specHeadings:
        specHeadings[fragment] = []
    if shorthand not in specHeadings[fragment]:
        specHeadings[fragment].append(shorthand)


def cleanSpecHeadings(headings):
    """Headings data was purposely verbose, assuming collisions even when there wasn't one.
    Want to keep the collision data for multi-page, so I can tell when you request a non-existent page,
    but need to collapse away the collision stuff for single-page."""
    for specHeadings in headings.values():
        for k, v in list(specHeadings.items()):
            if k[0] == "#" and len(v) == 1 and v[0][0:2] == "/#":
                # No collision, and this is either a single-page spec or a non-colliding front-page link
                # Go ahead and collapse them.
                specHeadings[k] = specHeadings[v[0]]
                del specHeadings[v[0]]