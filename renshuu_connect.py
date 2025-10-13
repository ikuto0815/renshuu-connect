#!/bin/env python
import uvicorn

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, PlainTextResponse

from enum import Enum
from pydantic import BaseModel
from typing import Literal, Any
import requests
from concurrent.futures import ProcessPoolExecutor
from collections import deque
import os
import sys

log = deque(maxlen=100)

class Action(str, Enum):
    version = "version"
    addNote = "addNote"
    canAddNotes = "canAddNotes"
    deckNames = "deckNames"
    modelNames = "modelNames"
    modelFieldNames = "modelFieldNames"
    storeMediaFile = "storeMediaFile"
    #multi = "multi"


class Note(BaseModel):
    fields: dict
    deckName: str

    def japanese(self):
        return self.fields["Japanese"].split("/")[0]

    def reading(self):
        japanese = self.fields["Japanese"].split("/")
        if japanese[-1] != "":
            return japanese[-1]
        else:
            return japanese[0]

    def english(self):
        return self.fields["English"]

    def jmdict(self):
        if "jmdictId" in self.fields.keys():
            return self.fields["jmdictId"]
        else:
            return None

class NoteParam(BaseModel):
    note: Note

class Notes(BaseModel):
    notes: list[Note]

class BaseRequest(BaseModel):
    action: Action
    version: Literal[2]
    key: str

class EmptyRequest(BaseRequest):
    action: Literal[Action.version, Action.deckNames, Action.modelNames, Action.modelFieldNames, Action.storeMediaFile]

class AddNoteRequest(BaseRequest):
    action: Literal[Action.addNote]
    params: NoteParam

class CanAddNotesRequest(BaseRequest):
    action: Literal[Action.canAddNotes]
    params: Notes

class StoreMediaFile(BaseRequest):
    action: Literal[Action.storeMediaFile]
    params: Any

class RenshuuApi():
    session: str
    baseurl: str = "https://api.renshuu.org/v1/"
    headers: dict

    def __init__(self, apikey: str):
        self.session = apikey
        self.headers = {"Authorization": f"Bearer {apikey}"}

    def japanese(self, term):
        if term["kanji_full"] == "":
            return [self.reading(term)]
        return [t["term"] for t in term["aforms"]] + [term["kanji_full"]]

    def reading(self, term):
        return term["hiragana_full"]

    def english(self, term):
        return term.select(".vdict_def_block")[0].get_text().strip()

    def apiError(self, response):
        if "error" in response and response["error"]:
            return {"result": None, "error": response["error"]}
        else:
            return None

    def schedules(self):
        response = requests.get(f"{self.baseurl}lists", headers=self.headers).json()
        if (e := self.apiError(response)): return e

        # get lists of groups of vocab lists
        lists = [x for x in response["termtype_groups"] if x["termtype"] == "vocab"][0] or None
        if not lists: return []

        # list of lists in "it:groupname:title" format
        lists = [[y["list_id"] + ":" + x["group_title"] + ":" + y["title"] for y in x["lists"]] for x in lists["groups"]]
        # flatten list
        lists = [x for xs in lists for x in xs]
        return lists

    def lookup(self, note: Note):
        response = requests.get(f"{self.baseurl}word/search?value={note.japanese()}", headers = self.headers).json()
        if (e := self.apiError(response)): return e

        # compare dictionary id first
        for t in response["words"]:
            if note.jmdict() == t["edict_ent"]:
                return t["id"]
        # compare kanji+reading as fallback
        for t in response["words"]:
            if (self.reading(t) == note.reading() and
                note.japanese() in self.japanese(t)):
                return t["id"]

    def canAddNote(self, note: Note):
        return True

    def addNote(self, note: Note):
        termId = self.lookup(note)

        listId = note.deckName.split(":")[0]

        #if listId not in [x.split(":")[0] for x in self.schedules()]:
        #    return

        if termId is not None:
            resp = requests.put(f"{self.baseurl}word/{termId}",
                               headers = self.headers, json = {"list_id": listId+""})
            if not resp.ok and resp.json()["error"] != "This term is already present in the schedule.":
                print(resp.content)
                content = {"result": None, "error": resp.json()["error"]}
                return JSONResponse(content=content, status_code=status.HTTP_200_OK)
            return 1
        print("no match")
        #raise HTTPException(status_code = 500, detail = "No matching entry found")

def register_exception(app: FastAPI):
    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        exc_str = f'{exc}'.replace('\n', ' ').replace('   ', ' ')
        #print(await request.json())
        content = {"result": None, "error": exc_str}
        return JSONResponse(content=content, status_code=status.HTTP_200_OK)

class LogOutput(object):
    def write(self, string):
        log.append(string)
        pass

    def isatty(self):
        return False

sys.stdout = LogOutput()
sys.stderr = LogOutput()

if os.name == 'nt':
    from pystray import Icon as icon, Menu as menu, MenuItem as item
    from PIL import Image, ImageDraw
    import psutil

    def on_clicked(icon, item):
        icon.stop()
        parent_pid = os.getpid()
        parent = psutil.Process(parent_pid)
        for child in parent.children(recursive=True):  # or parent.children() for recursive=False
            child.kill()
        parent.kill()
        sys.exit(0)

    icon('test', Image.open(os.path.dirname(__file__) + '/kao.png'), menu=menu(
        item(
            'Exit',
            on_clicked
            ))).run_detached()

app = FastAPI()

async def catch_exceptions_middleware(request: Request, call_next):
    try:
        return await call_next(request)
    except Exception as e:
        exc_str = f"{type(e).__name__} at line {e.__traceback__.tb_lineno} of {__file__}: {e}"
        print(exc_str)
        content = {"result": None, "error": exc_str}
        return JSONResponse(content=content, status_code=status.HTTP_200_OK)

app.middleware('http')(catch_exceptions_middleware)

register_exception(app)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/", response_class=PlainTextResponse)
async def root(showlog: str="0"):
    if showlog == "0":
        return ""
    msg = "Last 100 log messages:\n\n"
    msg += "".join(log)
    return msg

@app.get("/about", response_class=PlainTextResponse)
async def root(showlog: str = "0"):
    pid = os.getpid()
    return f"renshuu-connect is running!\nPID = {pid}"

@app.post("/")
async def root(request: EmptyRequest | AddNoteRequest | CanAddNotesRequest):
    api = RenshuuApi(request.key)

    if request.action is Action.deckNames:
        return api.schedules()
    elif request.action is Action.modelNames:
        return ["Default", "with jmdictId"]
    elif request.action is Action.modelFieldNames:
        return ["Japanese", "English", "jmdictId"]
    elif request.action is Action.canAddNotes:
        with ProcessPoolExecutor() as executor:
            resp = executor.map(api.canAddNote, request.params.notes)
        return list(resp)
    elif request.action is Action.addNote:
        return api.addNote(request.params.note)
    #elif request.action is Action.multi:
    #    return "TODO"
    elif request.action is Action.storeMediaFile:
        return ""
    elif request.action is Action.version:
        return 2

if __name__ == "__main__":
    uvicorn.run(app, port=8765, log_level="warning")
