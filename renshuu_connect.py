#!/bin/env python
import uvicorn

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from enum import Enum
from pydantic import BaseModel
from typing import Literal, Any
import requests
from concurrent.futures import ProcessPoolExecutor
import os

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

    def schedules(self):
        response = requests.get(f"{self.baseurl}word/1", headers=self.headers)
        if not response:
            print("Getting schedules failed, probably invalid API key")
            return "invalid api key"

        lists = response.json()["words"][0]["presence"]["lists"]
        return ["{}:{}".format(li["list_id"], li["name"]) for li in lists]

    def lookup(self, note: Note):
        response = requests.get(f"{self.baseurl}word/search?value={note.japanese()}", headers = self.headers).json()
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

        if note.deckName not in self.schedules():
            return

        listId = note.deckName.split(":")[0]
        if termId is not None:
            requests.put(f"{self.baseurl}word/{termId}",
                         headers = self.headers, json = {"list_id": listId})
            return 1
        print("no match")
        #raise HTTPException(status_code = 500, detail = "No matching entry found")

def register_exception(app: FastAPI):
    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        exc_str = f'{exc}'.replace('\n', ' ').replace('   ', ' ')
        #print(await request.json())
        content = {'status_code': 10422, 'message': exc_str, 'data': None}
        return JSONResponse(content=content, status_code=status.HTTP_200_OK)

if os.name == 'nt':
    # Are we running in a PyInstaller bundle
    # https://pyinstaller.org/en/stable/runtime-information.html#run-time-information
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        class NullOutput(object):
            def write(self, string):
                pass

            def isatty(self):
                return False


        sys.stdout = NullOutput()
        sys.stderr = NullOutput()

    from pystray import Icon as icon, Menu as menu, MenuItem as item
    from PIL import Image, ImageDraw
    import psutil

    def create_image(width, height, color1, color2):
        # Generate an image and draw a pattern
        image = Image.new('RGB', (width, height), color1)
        dc = ImageDraw.Draw(image)
        dc.rectangle(
            (width // 2, 0, width, height // 2),
            fill=color2)
        dc.rectangle(
            (0, height // 2, width // 2, height),
            fill=color2)

        return image

    def on_clicked(icon, item):
        icon.stop()
        parent_pid = os.getpid()
        parent = psutil.Process(parent_pid)
        for child in parent.children(recursive=True):  # or parent.children() for recursive=False
            child.kill()
        parent.kill()
        sys.exit(0)

    icon('test', create_image(64, 64, 'black', 'white'), menu=menu(
        item(
            'Exit',
            on_clicked
            ))).run_detached()

app = FastAPI()

register_exception(app)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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
