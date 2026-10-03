"""SENTINEL AI: plain-language explanations on top of the screening system.

The language model EXPLAINS; it never decides. Every verdict, score and reason
code still comes from src/pipeline.py and the agent team. What this package
adds is wording:

    facts.py     grounded fact sheets built ONLY from what the API already serves
    llm.py       the Mistral chat client (optional; off without MISTRAL_API_KEY)
    narrator.py  summaries and Q&A, number-checked against the facts, cached,
                 with a deterministic built-in summary whenever the model is
                 unavailable or its answer fails the check

The number check is the accuracy guarantee: any number in the model's answer
that does not appear in the facts (allowing rounding and fraction/percentage
conversion) causes the answer to be discarded and the built-in summary used.
"""
