"""Survey comment templates.

Comments are assembled from the claim's actual experience, so free-text themes are
grounded in the same planted causes as the structured data. Deterministic: no LLM.
"""

THEMES: dict[str, list[str]] = {
    "documents": [
        "Had to upload my documents twice, nobody told me upfront what was missing.",
        "Was asked for additional papers after I had already submitted everything.",
        "The document list should be shared at the start, not after a week.",
        "Got a call asking for one more document, then another one later. Very frustrating.",
        "My broker submitted the claim but the papers were incomplete, so it got stuck.",
        "Why can't you tell me all the documents needed in one go?",
    ],
    "approval_wait": [
        "Claim was approved by the team but then waited days for a senior to sign off.",
        "Everything was done and it was just sitting for approval. No updates.",
        "Was told it is pending with the senior adjuster for almost a week.",
        "The final approval took longer than the entire rest of the process.",
    ],
    "rework": [
        "Same questions were asked again by a different person.",
        "They verified my claim, then called again to re-verify the same details.",
        "Felt like my file went back and forth internally.",
    ],
    "slow_general": [
        "Took much longer than the 5 days I was promised.",
        "Too slow. I had to follow up multiple times.",
        "Settlement got delayed and I had to keep calling customer care.",
        "No clear timeline was given and it dragged on.",
    ],
    "surveyor": [
        "Surveyor visit got rescheduled, garage was waiting for days.",
        "The surveyor came late and the report took time.",
    ],
    "weekend": [
        "Nothing moved over the weekend, lost three days for no reason.",
        "Submitted on Friday evening and nobody looked at it till Monday afternoon.",
    ],
    "positive": [
        "Smooth process, settled quickly. Thank you.",
        "Very happy with the speed of settlement.",
        "Hassle-free claim, the team was helpful.",
        "Quick and transparent. Will recommend.",
        "Good experience overall, kept me informed.",
    ],
    "neutral": [
        "Process was okay, could be faster.",
        "Fine overall, some delays in between.",
        "Average experience.",
    ],
}


def pick(theme: str, u: float) -> str:
    options = THEMES[theme]
    return options[min(int(u * len(options)), len(options) - 1)]
