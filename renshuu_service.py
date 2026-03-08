from models import Note, CanAddNotesErrorDetail
from renshuu_api import RenshuuApi
from db_models import Word, ListMembership
from sqlalchemy.orm import Session
from typing import Optional, List
import logging
import re

logger = logging.getLogger(__name__)


class RenshuuService:
    """Service layer for Renshuu operations with caching and business logic."""
    
    def __init__(self, api: RenshuuApi, db: Session):
        self.api = api
        self.db = db

    def _extract_japanese(self, term: dict) -> List[str]:
        """Extract Japanese forms from API term object."""
        if term.get("kanji_full") == "":
            return [self._extract_reading(term)]
        japanese_forms = [t["term"] for t in term.get("aforms", [])]
        if term.get("kanji_full"):
            japanese_forms.append(term["kanji_full"])
        return japanese_forms

    def _extract_reading(self, term: dict) -> str:
        """Extract reading from API term object."""
        return term.get("hiragana_full", "")

    def _is_list_cached(self, list_id: str) -> bool:
        """Check if we have cached any words for this list."""
        count = self.db.query(ListMembership).filter(
            ListMembership.list_id == list_id
        ).count()
        return count > 0

    def _cache_word(self, word_data: dict) -> Word:
        """Cache a word from API response into database."""
        renshuu_id = word_data.get("id")
        if not renshuu_id:
            return None

        renshuu_id = str(renshuu_id)

        word = self.db.query(Word).filter(Word.renshuu_id == renshuu_id).first()
        
        if word:
            word.japanese = word_data.get("kanji_full", "")
            word.reading = self._extract_reading(word_data)
            word.jmdict_id = word_data.get("edict_ent")
        else:
            word = Word(
                renshuu_id=renshuu_id,
                japanese=word_data.get("kanji_full", ""),
                reading=self._extract_reading(word_data),
                jmdict_id=word_data.get("edict_ent")
            )
            self.db.add(word)
        
        return word

    def _cache_list_membership(self, list_id: str, renshuu_id: str):
        """Cache a list membership, avoiding duplicates."""
        existing = self.db.query(ListMembership).filter(
            ListMembership.list_id == list_id,
            ListMembership.renshuu_id == renshuu_id
        ).first()
        
        if not existing:
            membership = ListMembership(
                list_id=list_id,
                renshuu_id=renshuu_id
            )
            self.db.add(membership)

    def _cache_words_from_response(self, response: dict):
        """Proactively cache all words from API search response."""
        if "words" not in response:
            return
        
        for word_data in response["words"]:
            self._cache_word(word_data)
        
        self.db.commit()

    def _is_vocab_term(self, term: dict) -> bool:
        """Check if a term from list contents is a vocab word."""
        return (
            "id" in term and
            "kanji_full" in term and
            "hiragana_full" in term and
            "kanji" not in term and
            "title_english" not in term and
            "japanese" not in term
        )

    def _fetch_and_cache_list_contents(self, list_id: str):
        """
        Fetch all pages of a list and cache all vocab words and their memberships.
        This is called when we first encounter a list.
        """
        logger.info(f"Fetching and caching list contents for list_id: {list_id}")
        page = 1
        nr_terms = None
        total_pages = None
        
        while True:
            response = self.api.get_list_contents(list_id, page)
            
            if "error" in response:
                logger.error(f"Error fetching list {list_id} page {page}: {response.get('error')}")
                break
            
            contents = response.get("contents", {})
            terms = contents.get("terms", [])
            
            if page == 1:
                nr_terms = response.get("num_terms", 0)
                total_pages = contents.get("total_pg", 1)
            
            for term in terms:
                if self._is_vocab_term(term):
                    word = self._cache_word(term)
                    if word:
                        self._cache_list_membership(list_id, word.renshuu_id)
            
            if page >= total_pages:
                break
            
            page += 1
        
        self.db.commit()
        logger.info(f"Finished caching list contents for list_id: {list_id}, {total_pages} pages cached, {nr_terms} terms cached")

    def lookup_word(self, note: Note) -> Optional[str]:
        """
        Look up a word for a note, checking cache first, then API.
        Returns renshuu_id if found, None otherwise.
        """
        # Prefer jmdict_id
        jmdict_id = note.jmdict()
        if jmdict_id:
            word = self.db.query(Word).filter(Word.jmdict_id == jmdict_id).first()
            if word:
                return word.renshuu_id

        # Check cache by (japanese, reading) combination
        japanese = note.japanese()
        reading = note.reading()
        word = self.db.query(Word).filter(
            Word.japanese == japanese,
            Word.reading == reading
        ).first()
        
        if word:
            return word.renshuu_id

        response = self.api.search_words(japanese)
        
        if "error" in response:
            return None
        
        if "words" not in response or not response["words"]:
            return None

        # Proactively cache all returned words
        self._cache_words_from_response(response)

        # Match note to word using jmdict_id
        if jmdict_id:
            for word_data in response["words"]:
                if word_data.get("edict_ent") == jmdict_id:
                    return word_data.get("id")

        # Fallback: match by kanji+reading
        for word_data in response["words"]:
            word_reading = self._extract_reading(word_data)
            word_japanese_forms = self._extract_japanese(word_data)
            
            if word_reading == reading and japanese in word_japanese_forms:
                return word_data.get("id")

        return None

    def add_note(self, note: Note):
        """
        Add a note to a list.
        Returns result or error dictionary.
        """
        term_id = self.lookup_word(note)
        
        if term_id is None:
            logger.warning(f"Could not find word for note: {note.japanese()}")
            return None

        list_id = note.deckName.split(":")[0]
        logger.debug(f"Adding note to list {list_id}, term_id: {term_id}")

        # fetch and cache l its contents
        if not self._is_list_cached(list_id):
            self._fetch_and_cache_list_contents(list_id)

        # Check cache if word is already in list
        membership = self.db.query(ListMembership).filter(
            ListMembership.list_id == list_id,
            ListMembership.renshuu_id == term_id
        ).first()
        
        if membership:
            # Already in list, return success
            logger.debug(f"Word {term_id} already in list {list_id}")
            return 1

        # Not cached, call API
        resp = self.api.add_word_to_list(term_id, list_id)
        
        if not resp.ok:
            resp_json = resp.json()
            if resp_json.get("error") != "This term is already present in the schedule.":
                return {"result": None, "error": resp_json.get("error")}

        existing = self.db.query(ListMembership).filter(
            ListMembership.list_id == list_id,
            ListMembership.renshuu_id == term_id
        ).first()
        if not existing:
            membership = ListMembership(
                list_id=list_id,
                renshuu_id=term_id
            )
            self.db.add(membership)
            self.db.commit()
        return 1

    def can_add_note(self, _note: Note) -> bool:
        # To conserve API calls we always return True
        return True

    def _lookup_word_cache_only(self, note: Note) -> Optional[str]:
        """
        Look up a word in cache only, without calling the API.
        Returns renshuu_id if found in cache, None otherwise.
        """
        # Prefer jmdict_id
        jmdict_id = note.jmdict()
        if jmdict_id:
            word = self.db.query(Word).filter(Word.jmdict_id == jmdict_id).first()
            if word:
                return word.renshuu_id

        # Check cache by (japanese, reading) combination
        japanese = note.japanese()
        reading = note.reading()
        word = self.db.query(Word).filter(
            Word.japanese == japanese,
            Word.reading == reading
        ).first()
        
        if word:
            return word.renshuu_id

        return None

    def can_add_notes_with_error_detail(self, note: Note) -> CanAddNotesErrorDetail:
        """
        Check if a note can be added by checking only the local cache.
        Returns False with error detail if the term is already in the list.
        """
        term_id = self._lookup_word_cache_only(note)
        
        if term_id is not None:
            list_id = note.deckName.split(":")[0]
            
            membership = self.db.query(ListMembership).filter(
                ListMembership.list_id == list_id,
                ListMembership.renshuu_id == term_id
            ).first()
            
            if membership:
                return CanAddNotesErrorDetail(
                    canAdd=False,
                    error="cannot create note because it is a duplicate"
                )
        
        return CanAddNotesErrorDetail(canAdd=True, error=None)

    def get_schedules(self) -> List[str]:
        """
        Get formatted list of schedules.
        Returns list in "it:groupname:title" format.
        """
        response = self.api.get_lists()
        
        if "error" in response:
            return response

        termtype_groups = response.get("termtype_groups", [])
        vocab_group = next(
            (x for x in termtype_groups if x.get("termtype") == "vocab"),
            None
        )
        
        if not vocab_group:
            return []

        groups = vocab_group.get("groups", [])
        formatted_lists = []
        for group in groups:
            group_title = group.get("group_title", "")
            lists = group.get("lists", [])
            for list_item in lists:
                list_id = list_item.get("list_id", "")
                title = list_item.get("title", "")
                formatted_lists.append(f"{list_id}:{group_title}:{title}")
        
        return formatted_lists

    def drop_list_cache(self, list_id: str) -> dict:
        """
        Drop all cached data for a specific list.
        Deletes all ListMembership records with the given list_id.
        Returns a dictionary with the count of deleted records.
        """
        count = self.db.query(ListMembership).filter(
            ListMembership.list_id == list_id
        ).count()
        
        self.db.query(ListMembership).filter(
            ListMembership.list_id == list_id
        ).delete()
        
        self.db.commit()
        
        return {"deleted_count": count, "list_id": list_id}

    def _parse_find_notes_query(self, query: str) -> dict:
        """
        Parse a findNotes query string.
        Supports Anki-style queries like: "deck:blahblah:blah:blah" "japanese:読む/よむ"
        Returns a dict with 'list_id' and 'japanese'
        """
        result = {"list_id": None, "japanese": None}
        
        # Extract quoted strings from the query
        quoted_strings = re.findall(r'"([^"]*)"', query)
        
        for quoted_str in quoted_strings:
            # Check for deck: prefix
            if quoted_str.startswith("deck:"):
                # Extract list_id (first part after deck:)
                parts = quoted_str.split(":")
                if len(parts) > 1:
                    result["list_id"] = parts[1]
            # Check for japanese: prefix
            elif quoted_str.startswith("japanese:"):
                # Extract Japanese text (everything after japanese:)
                japanese_text = quoted_str[len("japanese:"):]
                # Handle format like "読む/よむ" - take the part before /
                if "/" in japanese_text:
                    result["japanese"] = japanese_text.split("/")[0]
                else:
                    result["japanese"] = japanese_text
        
        return result

    def find_notes(self, query: str) -> List[int]:
        """
        Find notes matching the query.
        Query format: "deck:list_id:..." "japanese:text"
        Returns a list of note IDs (renshuu_ids) that match the query.
        """
        parsed = self._parse_find_notes_query(query)
        list_id = parsed.get("list_id")
        japanese_reading = parsed.get("japanese")

        if '/' in japanese_reading:
            japanese = japanese_reading.split("/")[0]
            reading = japanese_reading.split("/")[1]
        else:
            japanese = japanese_reading
            reading = None 
        
        if not list_id or not japanese:
            logger.warning(f"findNotes query missing deck/list_id or japanese: {query}")
            return []
        
        # if not cached, just give up
        if not self._is_list_cached(list_id):
            return []
        
        # First, query Word table with japanese/reading filters
        # This is more efficient as it uses indexes on Word table first
        word_query = self.db.query(Word.renshuu_id).filter(Word.japanese == japanese)
        if reading:
            word_query = word_query.filter(Word.reading == reading)
        
        # Then check if those words are in the list via ListMembership
        query_builder = word_query.join(
            ListMembership,
            Word.renshuu_id == ListMembership.renshuu_id
        ).filter(
            ListMembership.list_id == list_id
        )
        
        # Hopefully there is only one, but we handle it
        results = query_builder.all()
        note_ids = [int(row[0]) for row in results if row[0]]

        logger.debug(f"findNotes found {len(note_ids)} notes for query: {query}: {note_ids}")
        
        return note_ids

