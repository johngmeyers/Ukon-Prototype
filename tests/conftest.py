from dotenv import load_dotenv

# Make ANTHROPIC_API_KEY from .env available to `pytest -m live`. Variables already set in
# the environment win. Unit tests never call the API, so they don't depend on this.
load_dotenv()
