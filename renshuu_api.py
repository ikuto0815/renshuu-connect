import requests
from typing import Optional, Dict, Any, List


class RenshuuApi:
    """API wrapper for renshuu.org API."""
    
    baseurl: str = "https://api.renshuu.org/v1/"
    headers: dict

    def __init__(self, apikey: str):
        self.headers = {"Authorization": f"Bearer {apikey}"}

    def apiError(self, response: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Check if API response contains an error."""
        if "error" in response and response["error"]:
            return {"result": None, "error": response["error"]}
        return None

    def search_words(self, value: str) -> Dict[str, Any]:
        """
        Search for words by value.
        Returns raw API response with list of word objects.
        """
        response = requests.get(
            f"{self.baseurl}word/search?value={value}",
            headers=self.headers
        ).json()
        
        error = self.apiError(response)
        if error:
            return error
        
        return response

    def get_lists(self) -> Dict[str, Any]:
        """
        Get all lists from the API.
        Returns raw API response.
        """
        response = requests.get(
            f"{self.baseurl}lists",
            headers=self.headers
        ).json()
        
        error = self.apiError(response)
        if error:
            return error
        
        return response

    def add_word_to_list(self, term_id: str, list_id: str) -> requests.Response:
        """
        Add a word to a list.
        Returns the raw requests.Response object.
        """
        return requests.put(
            f"{self.baseurl}word/{term_id}",
            headers=self.headers,
            json={"list_id": list_id}
        )

    def get_list_contents(self, list_id: str, page: int = 1) -> Dict[str, Any]:
        """
        Get contents of a list with pagination.
        Returns raw API response.
        """
        response = requests.get(
            f"{self.baseurl}list/{list_id}?pg={page}",
            headers=self.headers
        ).json()
        
        error = self.apiError(response)
        if error:
            return error
        
        return response
