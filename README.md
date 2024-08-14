# What is renshuu-connect?

Renshuu-connect is a small utility that makes it possible to take words looked up in the
Yomitan browser addon and add them to a vocabulary list on renshuu.org.

Yomichan already has an interface that is used to add cards to anki decks.
Renshuu-connect provides the same interface. This way yomichan can connect to it
without having to be modified.

# How to configure renshuu-connect

0. Go to ![the releases page](https://github.com/ikuto0815/renshuu-connect/releases) and download a release for your OS and run it.
1. Go to the yomitan addon settings.
2. Enable the advanced mode.

    ![advanced setting](01_advanced.png "Advanced setting")

3. Scroll to the "Anki" settings section.
    ![anki settings](02_anki_settings.png "Anki settings")
   1. Enter "http://127.0.0.1:8765" as "AnkiConnect server address".
   2. Enter your Renshuu API key in the "API key" field.
   3. Turn off "Check for card duplicates".
   4. Turn on "Enable Anki integration"

4. Click on "Configure Anki card templates"
    ![card templates](03_card_templates.png "card templates")
   1. Paste the following at the beginning of the text box:

    ```
    {{#*inline "sequence"}}
    {{~definition.sequence~}}
    {{/inline}}
    ```
5. Click on "Configure Anki card format…" 
    ![card format](04_cards.png "card format")
    Configure it as shown in the screenshot.
    With the "Deck" setting you can select one of your Renshuu lists that will be used to add new words.
