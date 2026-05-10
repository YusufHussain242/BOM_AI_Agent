from SPARQLWrapper import SPARQLWrapper, JSON
from typing import Optional, Literal

PREFIXES = """
PREFIX bom:  <http://ibom.ai/ontology/bom#>
PREFIX owl:  <http://www.w3.org/2002/07/owl#>
PREFIX rdf:  <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX xsd:  <http://www.w3.org/2001/XMLSchema#>
PREFIX data: <http://ibom.ai/data/bom#>
"""

sparql = SPARQLWrapper("http://localhost:3030/bom/query")


VALID_VARIANTS = ["SEDAN", "SUV", "COUPE", "HATCH", "ESTATE"]
VariantType = Literal["SEDAN", "SUV", "COUPE", "HATCH", "ESTATE"]

VALID_METRICS = ["total_parts", "total_weight", "total_cost"]
MetricType = Literal["total_parts", "total_weight", "total_cost"]


def performQuery(query):
    query_full = PREFIXES + query
    sparql.setQuery(query_full)
    sparql.setReturnFormat(JSON)
    results = sparql.query().convert()
    return results


# -------------------------------------------------------------------
# Helper utilities
# -------------------------------------------------------------------


def validate_variant(variant_code):
    if variant_code and variant_code not in VALID_VARIANTS:
        raise ValueError(
            f"Invalid variant_code '{variant_code}'. "
            f"Expected one of: {VALID_VARIANTS}"
        )


def build_variant_filter(variant_code):
    if variant_code:
        return f'?vehicle bom:variantCode "{variant_code}" .'
    return ""


def build_system_filter(system_name):
    if system_name:
        return f'FILTER(LCASE(STR(?systemName)) = LCASE("{system_name}"))'
    return ""


# -------------------------------------------------------------------
# Skill 1: count_parts
# -------------------------------------------------------------------


def count_parts(variant_code: VariantType, system_name: Optional[str] = None):
    """
    Calculates the total aggregate count of all physical parts within a vehicle variant's BOM.

    This tool accounts for part quantities (multipliers) within assemblies. Use this when 
    the user asks for the "total number of parts," "part sum," or "full component count."
    Do NOT use this if the user asks for "unique" or "distinct" parts.

    Args:
        variant_code: The short-code for the vehicle (e.g., 'SEDAN', 'SUV', 'COUPE', 'HATCH', 'ESTATE').
        system_name: The specific engineering system to filter by (e.g., 'Engine', 'Brakes'). 
                                     If omitted, calculates for the entire vehicle.

    Returns:
        dict: A summary containing the variant, system, and the integer total_parts.
    """

    validate_variant(variant_code)

    query = f"""
    SELECT (SUM(xsd:integer(?qty)) AS ?totalParts)
    WHERE {{
        ?vehicle bom:variantCode ?variantCode ;
                 bom:hasSystem ?system .

        {build_variant_filter(variant_code)}

        ?system bom:systemName ?systemName ;
                bom:hasAssembly ?assembly .

        {build_system_filter(system_name)}

        ?assembly bom:hasPart ?partLink .

        ?partLink bom:part ?part ;
                  bom:quantity ?qty .
    }}
    """

    results = performQuery(query)

    bindings = results["results"]["bindings"]
    total_parts = 0

    if bindings and bindings[0].get("totalParts"):
        total_parts = int(float(bindings[0]["totalParts"]["value"]))

    return {
        "variant_code": variant_code,
        "system_name": system_name,
        "total_parts": total_parts,
    }


# -------------------------------------------------------------------
# Skill 2: count_unique_parts
# -------------------------------------------------------------------


def count_unique_parts(variant_code: VariantType, system_name: Optional[str] = None):
    """
    Calculates the number of distinct (unique) part URIs within a vehicle variant's BOM.

    Unlike 'count_parts', this tool ignores quantity multipliers. Use this when the user 
    asks "how many different parts," "unique components," or "distinct part numbers" 
    are in the design. It represents the variety of parts rather than the total volume.

    Args:
        variant_code: The short-code for the vehicle (e.g., 'SEDAN', 'SUV', 'COUPE').
        system_name: Optional engineering system filter (e.g., 'Chassis & Frame').

    Returns:
        dict: Containing the variant, system, and integer count of unique parts.
    """

    validate_variant(variant_code)

    query = f"""
    SELECT (COUNT(DISTINCT ?part) AS ?uniqueParts)
    WHERE {{
        ?vehicle bom:variantCode ?variantCode ;
                 bom:hasSystem ?system .

        {build_variant_filter(variant_code)}

        ?system bom:systemName ?systemName ;
                bom:hasAssembly ?assembly .

        {build_system_filter(system_name)}

        ?assembly bom:hasPart ?partLink .

        ?partLink bom:part ?part .
    }}
    """

    results = performQuery(query)

    bindings = results["results"]["bindings"]
    unique_parts = 0

    if bindings and bindings[0].get("uniqueParts"):
        unique_parts = int(bindings[0]["uniqueParts"]["value"])

    return {
        "variant_code": variant_code,
        "system_name": system_name,
        "unique_parts": unique_parts,
    }


# -------------------------------------------------------------------
# Skill 3: most_complex_system
# -------------------------------------------------------------------


def most_complex_system(variant_code: Optional[VariantType] = None):
    """
    Identifies the single engineering system with the highest total part count (quantity-weighted).

    "Complexity" is defined by the sheer volume of parts. Use this for queries like 
    "Which system is the most complex?" or "What system has the most parts?". 

    Args:
        variant_code: The variant to check. If omitted, the tool searches 
                                     across all variants to find the most complex system overall.

    Returns:
        dict: The name of the most complex system and its total part count.
    """

    validate_variant(variant_code)

    query = f"""
    SELECT ?variantCode ?systemName
           (SUM(xsd:integer(?qty)) AS ?totalPartCount)
    WHERE {{
        ?vehicle bom:variantCode ?variantCode ;
                 bom:hasSystem ?system .

        {build_variant_filter(variant_code)}

        ?system bom:systemName ?systemName ;
                bom:hasAssembly ?assembly .

        ?assembly bom:hasPart ?partLink .

        ?partLink bom:part ?part ;
                  bom:quantity ?qty .
    }}
    GROUP BY ?variantCode ?systemName
    ORDER BY DESC(?totalPartCount)
    LIMIT 1
    """

    results = performQuery(query)

    bindings = results["results"]["bindings"]

    if not bindings:
        return {
            "variant_code": variant_code,
            "result": None,
        }

    row = bindings[0]

    return {
        "requested_variant": variant_code,
        "variant_code": row["variantCode"]["value"],
        "system_name": row["systemName"]["value"],
        "total_part_count": int(float(row["totalPartCount"]["value"])),
    }


# -------------------------------------------------------------------
# Skill 4: heaviest_system
# -------------------------------------------------------------------


def heaviest_system(variant_code: Optional[VariantType] = None, top_n: int = 1):
    """
    Identifies the system(s) with the highest total mass (quantity * unitWeightKg).

    Use this for queries regarding the weight of systems, such as "What is the heaviest system?" 
    or "List the top 3 heaviest systems in the SUV." Results are returned in kilograms (kg).

    Args:
        variant_code: Specific car variant to query.
        top_n: The number of top systems to return (defaults to 1).

    Returns:
        dict: A list of systems and their respective weights in kg.
    """

    validate_variant(variant_code)

    query = f"""
    SELECT ?variantCode ?systemName
           (SUM(xsd:decimal(?qty) * xsd:decimal(?weight)) AS ?totalWeightKg)
    WHERE {{
        ?vehicle bom:variantCode ?variantCode ;
                 bom:hasSystem ?system .

        {build_variant_filter(variant_code)}

        ?system bom:systemName ?systemName ;
                bom:hasAssembly ?assembly .

        ?assembly bom:hasPart ?partLink .

        ?partLink bom:part ?part ;
                  bom:quantity ?qty .

        ?part bom:unitWeightKg ?weight .
    }}
    GROUP BY ?variantCode ?systemName
    ORDER BY DESC(?totalWeightKg)
    LIMIT {int(top_n)}
    """

    results = performQuery(query)

    rows = []

    for row in results["results"]["bindings"]:
        rows.append({
            "variant_code": row["variantCode"]["value"],
            "system_name": row["systemName"]["value"],
            "total_weight_kg": round(
                float(row["totalWeightKg"]["value"]),
                2,
            ),
        })

    return {
        "requested_variant": variant_code,
        "top_n": top_n,
        "results": rows,
    }


# -------------------------------------------------------------------
# Skill 5: costliest_system
# -------------------------------------------------------------------


def costliest_system(variant_code: Optional[VariantType] = None, top_n: int = 1):
    """
    Identifies the system(s) with the highest total material cost (quantity * unitCostGBP).

    Use this for financial or procurement queries, such as "Which system costs the most?" 
    or "What are the most expensive systems in the Coupé?". Results are in GBP (£).

    Args:
        variant_code: Specific car variant to query.
        top_n: The number of top systems to return (defaults to 1).

    Returns:
        dict: A list of systems and their respective total costs in GBP.
    """

    validate_variant(variant_code)

    query = f"""
    SELECT ?variantCode ?systemName
           (SUM(xsd:decimal(?qty) * xsd:decimal(?cost)) AS ?totalCostGBP)
    WHERE {{
        ?vehicle bom:variantCode ?variantCode ;
                 bom:hasSystem ?system .

        {build_variant_filter(variant_code)}

        ?system bom:systemName ?systemName ;
                bom:hasAssembly ?assembly .

        ?assembly bom:hasPart ?partLink .

        ?partLink bom:part ?part ;
                  bom:quantity ?qty .

        ?part bom:unitCostGBP ?cost .
    }}
    GROUP BY ?variantCode ?systemName
    ORDER BY DESC(?totalCostGBP)
    LIMIT {int(top_n)}
    """

    results = performQuery(query)

    rows = []

    for row in results["results"]["bindings"]:
        rows.append({
            "variant_code": row["variantCode"]["value"],
            "system_name": row["systemName"]["value"],
            "total_cost_gbp": round(
                float(row["totalCostGBP"]["value"]),
                2,
            ),
        })

    return {
        "requested_variant": variant_code,
        "top_n": top_n,
        "results": rows,
    }


# -------------------------------------------------------------------
# Skill 6: compare_variants
# -------------------------------------------------------------------


def compare_variants(metric: MetricType, system_name: Optional[str] = None):
    """
    Performs a comparative analysis across all five Apex variants based on a specific metric.

    Use this when the user asks to "Compare variants," "Which variant is best for...", 
    or "Rank the cars by weight/cost." It provides a high-level overview of the entire platform.

    Args:
        metric: The metric to compare. Must be 'total_parts', 'total_weight', or 'total_cost'.
        system_name: Optional filter to compare variants only within a 
                                     specific system (e.g., 'Brakes').

    Returns:
        dict: A ranked list of all variants for the chosen metric.
    """

    if metric not in VALID_METRICS:
        raise ValueError(
            f"Invalid metric '{metric}'. "
            f"Expected one of: {VALID_METRICS}"
        )

    metric_expression = {
        "total_parts": "SUM(xsd:integer(?qty))",
        "total_weight": "SUM(xsd:decimal(?qty) * xsd:decimal(?weight))",
        "total_cost": "SUM(xsd:decimal(?qty) * xsd:decimal(?cost))",
    }

    metric_alias = {
        "total_parts": "metricValue",
        "total_weight": "metricValue",
        "total_cost": "metricValue",
    }

    optional_weight = ""
    optional_cost = ""

    if metric == "total_weight":
        optional_weight = "?part bom:unitWeightKg ?weight ."

    if metric == "total_cost":
        optional_cost = "?part bom:unitCostGBP ?cost ."

    query = f"""
    SELECT ?variantCode
           ({metric_expression[metric]} AS ?{metric_alias[metric]})
    WHERE {{
        ?vehicle bom:variantCode ?variantCode ;
                 bom:hasSystem ?system .

        ?system bom:systemName ?systemName ;
                bom:hasAssembly ?assembly .

        {build_system_filter(system_name)}

        ?assembly bom:hasPart ?partLink .

        ?partLink bom:part ?part ;
                  bom:quantity ?qty .

        {optional_weight}
        {optional_cost}
    }}
    GROUP BY ?variantCode
    ORDER BY DESC(?metricValue)
    """

    results = performQuery(query)

    rows = []

    for row in results["results"]["bindings"]:
        value = float(row["metricValue"]["value"])

        if metric == "total_parts":
            value = int(value)
        else:
            value = round(value, 2)

        rows.append({
            "variant_code": row["variantCode"]["value"],
            metric: value,
        })

    return {
        "metric": metric,
        "system_name": system_name,
        "results": rows,
    }


SKILLS = [count_parts, count_unique_parts, most_complex_system,
          heaviest_system, costliest_system, compare_variants]
