from enum import Enum
from pydantic import BaseModel, ConfigDict, TypeAdapter
from typing import Literal, Any, Optional, Union


class CanAddNotesErrorDetail(BaseModel):
    model_config = ConfigDict(exclude_none=True)

    canAdd: bool
    error: Optional[str] = None


class Action(str, Enum):
    version = "version"
    addNote = "addNote"
    canAddNotes = "canAddNotes"
    canAddNotesWithErrorDetail = "canAddNotesWithErrorDetail"
    deckNames = "deckNames"
    modelNames = "modelNames"
    modelFieldNames = "modelFieldNames"
    storeMediaFile = "storeMediaFile"
    findNotes = "findNotes"
    multi = "multi"
    guiBrowse = "guiBrowse"


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
    action: Literal[Action.version, Action.deckNames,
                    Action.modelNames, Action.modelFieldNames, Action.storeMediaFile, Action.guiBrowse]


class AddNoteRequest(BaseRequest):
    action: Literal[Action.addNote]
    params: NoteParam


class CanAddNotesRequest(BaseRequest):
    action: Literal[Action.canAddNotes]
    params: Notes


class CanAddNotesWithErrorDetailRequest(BaseRequest):
    action: Literal[Action.canAddNotesWithErrorDetail]
    params: Notes


class FindNotesParams(BaseModel):
    query: str


class FindNotesRequest(BaseRequest):
    action: Literal[Action.findNotes]
    params: FindNotesParams


class StoreMediaFile(BaseRequest):
    action: Literal[Action.storeMediaFile]
    params: Any


# Union type for all possible request types (excluding MultiRequest to avoid recursion)
RequestUnion = Union[
    EmptyRequest,
    AddNoteRequest,
    CanAddNotesRequest,
    CanAddNotesWithErrorDetailRequest,
    FindNotesRequest,
]

# TypeAdapter for automatic validation of union types
_request_adapter = TypeAdapter(RequestUnion)


class MultiActionRequest(BaseModel):
    action: Action
    params: Optional[Any] = None

    def to_request(self, key: str) -> RequestUnion:
        """Construct a "fake request" from a MultiActionRequest."""
        request_data = {
            "action": self.action,
            "version": 2,
            "key": key
        }
        if self.params is not None:
            request_data["params"] = self.params

        # Use TypeAdapter to automatically validate against the union type
        # Pydantic will determine which request type matches and validate accordingly
        return _request_adapter.validate_python(request_data)


class MultiParams(BaseModel):
    actions: list[MultiActionRequest]


class MultiRequest(BaseRequest):
    action: Literal[Action.multi]
    params: MultiParams
