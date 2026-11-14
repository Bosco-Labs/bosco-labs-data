# LlamaIndex with Bosco Labs SEC EDGAR Filings Feed (bosco_labs/sec-filings-feed).
# Docs: https://docs.apify.com/platform/integrations/llama-index
# Checked against llama-index-core 0.14.25, llama-index-readers-apify 0.6.0,
# llama-index-llms-anthropic 0.12.3 (imports and signatures only; no live run).
#
#   pip install llama-index-core llama-index-readers-apify llama-index-llms-anthropic
#   export APIFY_TOKEN=...        # https://console.apify.com/settings/integrations
#   export ANTHROPIC_API_KEY=...
import os

from llama_index.core import Document, Settings, SummaryIndex
from llama_index.llms.anthropic import Anthropic
from llama_index.readers.apify import ApifyActor

Settings.llm = Anthropic(model="claude-opus-5-5", max_tokens=16000)

# One Document per filing: Nvidia's last 8 earnings releases (8-K Item 2.02).
docs = ApifyActor(os.environ["APIFY_TOKEN"]).load_data(
    actor_id="bosco_labs/sec-filings-feed",
    run_input={"tickers": ["NVDA"], "earningsReleasesOnly": True, "maxResults": 8},
    dataset_mapping_function=lambda item: Document(
        text=(
            f"{item['company_name']} filed a {item['form']} on {item['filing_date']}, "
            f"accepted at {item['accepted_at']} ({item['market_timing']}), "
            f"items: {', '.join(item['items'])}."
        ),
        metadata={"url": item["primary_document_url"]},
    ),
)

# SummaryIndex sends every document to the LLM: no embedding model needed for a handful of rows.
engine = SummaryIndex.from_documents(docs).as_query_engine()
print(engine.query("Does Nvidia release earnings before the open or after the close? List the dates."))
