#!/bin/env python
import uvicorn
import logging
from logging.handlers import RotatingFileHandler

from fastapi import FastAPI, Request, status, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, PlainTextResponse
from typing import Any

from models import (
    Action, EmptyRequest, AddNoteRequest, CanAddNotesRequest,
    CanAddNotesWithErrorDetailRequest, FindNotesRequest, MultiRequest, MultiActionRequest, BaseRequest, RequestUnion
)
from renshuu_api import RenshuuApi
from renshuu_service import RenshuuService
from database import init_db, get_db
from sqlalchemy.orm import Session
from contextlib import asynccontextmanager
import os


def setup_logging():
    # Use DATA_DIR environment variable if set, otherwise use current directory
    log_dir = os.getenv("LOGS_DIR", "logs")
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, "renshuu_connect.log")

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)

    # Create handlers
    root_logger.handlers.clear()

    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # Console handler - DEBUG level for verbose console output
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.DEBUG)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=1 * 1024 * 1024,  # 1MB
        backupCount=5,
        encoding='utf-8'
    )
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)

    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

    return root_logger


logger = setup_logging()


def register_exception(app: FastAPI):
    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        exc_str = f'{exc}'.replace('\n', ' ').replace('   ', ' ')
        logger.warning(f"Validation error: {exc_str}")
        logger.debug(f"Failing request body: {await request.body()}")
        content = {"result": None, "error": exc_str}
        return JSONResponse(content=content, status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    logger.debug("Initializing database...")
    init_db()
    yield


app = FastAPI(lifespan=lifespan)


async def catch_exceptions_middleware(request: Request, call_next):
    try:
        return await call_next(request)
    except Exception as e:
        exc_str = f"{type(e).__name__} at line {e.__traceback__.tb_lineno} of {__file__}: {e}"
        logger.error(exc_str, exc_info=True)
        content = {"result": None, "error": exc_str}
        return JSONResponse(content=content, status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)

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
async def root():
    return ""


@app.get("/about", response_class=PlainTextResponse)
async def about():
    pid = os.getpid()
    return f"renshuu-connect is running!\nPID = {pid}"


@app.delete("/drop_cache/{list_id}")
async def drop_cache(list_id: str, db: Session = Depends(get_db)):
    """
    Drop the cache for a specific list.
    Deletes all ListMembership records with the given list_id.
    """

    from renshuu_api import RenshuuApi
    api = RenshuuApi("")
    service = RenshuuService(api, db)

    result = service.drop_list_cache(list_id)
    return result


def handle_action(request: RequestUnion, service: RenshuuService) -> Any:
    """
    Handle a single action request and return the result.
    This function is used both for regular requests and for sub-actions in multi requests.
    """
    logger.debug(f'Handling action: {request.action}')

    if request.action is Action.deckNames:
        return service.get_schedules()
    elif request.action is Action.modelNames:
        return ["Default", "with jmdictId"]
    elif request.action is Action.modelFieldNames:
        return ["Japanese", "English", "jmdictId"]
    elif request.action is Action.canAddNotes:
        # Note: ProcessPoolExecutor can't share database sessions
        # TODO: We can parallelize the API requests, although in the same thread, API is mostly IO bound
        resp = [service.can_add_note(note)
                for note in request.params.notes]
        return resp
    elif request.action is Action.canAddNotesWithErrorDetail:
        resp = [service.can_add_notes_with_error_detail(
            note) for note in request.params.notes]
        return resp
    elif request.action is Action.addNote:
        return service.add_note(request.params.note)
    elif request.action is Action.findNotes:
        return service.find_notes(request.params.query)
    elif request.action is Action.storeMediaFile:
        return ""
    elif request.action is Action.version:
        return 2
    elif request.action is Action.guiBrowse:
        return []
    else:
        logger.debug(f"Unhandled action: {request.action}")
        return None


@app.post("/")
async def root(
    request: EmptyRequest | AddNoteRequest | CanAddNotesRequest | CanAddNotesWithErrorDetailRequest | FindNotesRequest | MultiRequest,
    db: Session = Depends(get_db)
):
    api = RenshuuApi(request.key)
    service = RenshuuService(api, db)

    logger.debug(f'Request action: {request.action}')

    # Handle multi action
    if request.action is Action.multi:
        results = []
        for action_request in request.params.actions:
            sub_request = action_request.to_request(request.key)
            result = handle_action(sub_request, service)
            results.append(result)
        return results

    # Handle regular single actions
    return handle_action(request, service)

if __name__ == "__main__":
    if os.name == 'nt':
        import windows
        windows.setup_tray_icon()
    logger.info("Starting renshuu-connect server on port 8765")
    uvicorn.run(app, port=8765, log_config=None)
