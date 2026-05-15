# Setup Instructions

## Clone Repository
```
git clone git@github.com:YusufHussain242/BOM_AI_Agent.git
```

## Setup Apache Fuseki Server

### 1.
Run the following in the project directory to create the fuseki server:

```
docker run -d \
  --name fuseki \
  -p 3030:3030 \
  -e ADMIN_PASSWORD=admin123 \
  stain/jena-fuseki
```

Note that you must have docker installed for this to work.

### 2.

Open a browser and navigate to http://localhost:3030.

Create a dataset called "bom"

Navigate to the "Add data page" and upload apex_bom.ttl and ontology.ttl to the default graph.

### 3.

Create a virtual environment and pip install the necessary requirements:

```
python -m venv ./venv
```

or

```
python3 -m venv ./venv
```

then

```
source ./venv/bin/activate
```

```
pip install requirements.txt
```


### 4.

Create a ```.env``` file and use the following template, filling out details as necessary:

```
GOOGLE_API_KEY=""
```

The ```GOOGLE_API_KEY``` can be provided upon requirest.

### 5.

Run the program with:
```
python agent.py
``` 
