import json
import os
import re
import sys
import sqlite3

import sqlite_utils


DB_PATH = "webui.db"

# columns: useful for getting table columns. input 1: table name.
ACTIONS = """
tables: useful for getting the names of tables available. no input.
schema: useful for looking at the schema of a database. input 1: table name.
help: useful for getting helpful context about how to use tables and their columns. input 1: table name. (optional) input 2: column name.
sql-query: useful for analyzing data and getting the top 5 results of a query. input 1: a valid sqlite sql query.
"""

'''
DATA_HELP EXAMPLE:
"users": {
    # table description
    None: "profiles of individuals (sometimes called creators) who are seeking work, have worked on projects, or are looking to hire other people.",
    "creatorUserId": "this is the primary key for a user. the experiences table references it on the creatorUserId field",
    "createdUtc": "a ISO8601 datetime string of the user creation date",
    "updatedUtc": "a ISO8601 datetime string of the user's last updated date",
    "isPublic": "a boolean describing if the user's profile is public. all of these values will be true",
    "isContactAllowed": "a boolean describing whether or not the user allows people to contact them",
    "creatorDescription": "a free-text field the user has supplied describing themselves, their interests, work preferences and occasionally age/location. details like this are sometimes present: 'I am 23 years old' or 'been building games for 8 years'.",
    "isOpenToWork": "whether or not the user is actively looking for work",
    "interestDescription": "a text field describing the users interests",
    "linkTypes": "an array of platforms/methods the users can be contacted on",
    "preferredContactLinkType": "the user's preferred platform/method of contact",
    "socialLinks": "an array of JSON data describing the user's social media accounts",
    "jobTypes": "the type of jobs and work the user is seeking",
    "skillTypes": "an array containing skills the user has",
    "requiresAction": "always set to \"noAction\"",
},
'''
DATA_HELP = {
    "auth": {
        # table description
        None: "Authorized users of the Fury.AI AI chat user interface",
        "id": "This is the primary key for a authorized user.",
        "email": "This is the email of the authorized user.",
        "password": "This is the hashed password of the user.",
        "active": "This indicates weather the user is an active user to the frontend interface.",
    },
    "chat": {
        # table description
        None: "This table stores all the chats of users with large language models.",
        "id": "The id of the chat.",
        "user_id": "The user id of the user who owns the chat.",
        "title": "The title of the conversation the user is having with the LLM.",
        "chat": "This includes the entire chat history between the user and the LLM. The values here are represented in a JSON string with various information of the model and user.",
        "share_id": "This is the id of another user who has been shared this chat.",
        "archived": "This includes information of if the chat has been archived.",
        "created_at": "This is when the chat was created.",
        "updated_at": "This is when the chat was updated.",
    },
    "document": {
        # table description
        None: "This table shows the documents that have been stored on Fury.AI used by LLMs for RAG.",
        "id": "This is the primary key in the table for the document tuple.",
        "collection_name": "This is the collection id where the document is stored. Each document is placed in it's own collection.",
        "name": "This is the name of the document.",
        "title": "This is the title of the document.",
        "filename": "This is the file name of the document.",
        "content": "This is always NULL.",
        "user_id": "This is the id if the user that uploaded the document.",
        "timestamp": "This is the timestamp of when the document was uploaded.",
    },
    "file": {
        # table description
        None: "This table holds records of files users have uploaded to a chat with a LLM.",
        "id": "This is the primary key for the table.",
        "user_id": "This is the id of the user who uploaded the file to one of their chats with a LLM.",
        "filename": "This is the filename of the uploaded document,",
        "meta": "This is metadata for the file uploaded which includes the name of the file, the file type, the size, and the path where the file is stored.",
        "created_at": "This is the time when the file was uploaded in integer format.",
    },
    "model": {
        # table description
        None: "This table holds records of models available to chat with on the Fury.AL AI chat system.",
        "id": "This is the primary key of the table.",
        "user_id": "This is the id of the user that downloaded the model.",
        "base_model_id": "This will show if the current model on the record is based off another model in this record. These are called custom models.",
        "name": "This is the name of the model.",
        "meta": "This includes metadata of the model with information like description, capabilities, suggestion prompts, and knowledge.",
        "params": "These are the parameters the model starts off with.",
        "created_at": "This is when the model was created.",
        "updated_at": "This is when the model was updated.",
    },
    "prompt": {
        # table description
        None: "This table holds records of prompts available for users to pass to a LLM with the hotkey '/' followed by the prompt title.",
        "id": "This is the primary key for this table.",
        "command": "This is the command the user has to run the activate and run this prompt.",
        "user_id": "This is the id of the user who created the prompt.",
        "title": "This is the title of the prompt.",
        "content": "This is the content of the prompt that will be passed to the LLM during a chat.",
        "timestamp": "This is the timestamp of when the prompt was created.",
    },
    "user": {
        # table description
        None: "This table includes information about users of the Fury.AI Ai chat system.",
        "id": "This is the primary key of the table and the users id.",
        "name": "This is the name of the user.",
        "email": "This is the email of the user.",
        "role": "This is the role of the user whether admin or standard user.",
        "profile_image_url": "This is the url of the profile image of the user.",
        "api_key": "always NULL.",
        "created_at": "This is when the user was created.",
        "updated_at": "This is when the user was updated.",
        "last_active_at": "This is when the user was last active on the system.",
        "settings": "These are profile settings of the user.",
        "info": "always NULL.",
        "oauth_sub": "always NULL.",
    },
}

IGNORED_TABLES = [
    "alembic_version",
    "chatidtag",
    "config",
    "function",
    "memory",
    "migratehistory",
    "tag",
    "tool"
]
IGNORED_COLUMNS = []


def load_db(path):
    assert os.path.exists(path), f"Database doesn't exist: {path}"
    db = sqlite_utils.Database(path)
    return db


def clean_truncate(results, n=3):
    return [
        {k: v for k, v in r.items()}
        for r in results[:n]
    ]


## ACTIONS
def tables(db):
    return [
        name
        for name in db.table_names()
        # game stats confuses the model
        if (
            "_fts" not in name
            and name not in IGNORED_TABLES
            and not name.endswith("_history")
        )
    ]


def schema(db, table_name):
    table_names = tables(db)
    if table_name not in table_names:
        return f"Error: Invalid table. Valid tables are: {table_names}"
    return re.sub('\s+', ' ', db[table_name].schema)


def columns(db, table_name):
    table_names = tables(db)
    if table_name not in table_names:
        return f"Error: Invalid table. Valid tables are: {table_names}"
    return [
        c.name
        for c in db[table_name].columns
        if c.name not in IGNORED_COLUMNS
    ]


def help(db, *args):
    if not args:
        return "Error: The help action requires at least one argument"
    table_name = args[0]
    column = None
    if len(args) == 2:
        column = args[1]
    if table_name not in DATA_HELP:
        available_tables = tables(db)
        return f"Error: The table {table_name} doesn't exist. Valid tables: {available_tables}"
    if column not in DATA_HELP[table_name]:
        available_columns = [
            c.name
            for c in db[table_name].columns
            if c.name not in IGNORED_COLUMNS
        ]
        return f"Error: The column {column} isn't in the {table_name} table. Valid columns: {available_columns}"
    help_text =  DATA_HELP[table_name][column]
    # table help requested
    if column is None:
        return help_text
    # column help requested, add common values
    analysis = db[table_name].analyze_column(column, common_limit=2)
    common_values = ", ".join([f"{value}" for value, count in analysis.most_common])
    return f"{help_text} the top two values are: {common_values}"


def sql_query(db, query):
    if query.lower().startswith("select *"):
        return "Error: Select some specific columns, not *"
    try:
        results = list(db.query(query))
    except sqlite3.OperationalError as e:
        return f"Your query has an error: {e}"
    return clean_truncate(results, n=5)
