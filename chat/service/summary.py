from chat.service.llm import call_deepseek

SUMMARY_PROMPT = (
    "You maintain a running summary of a conversation between a user and an "
    "assistant. Update the summary below to incorporate the new exchange. Keep it "
    "concise (a few sentences), preserving facts, preferences, and context that "
    "might matter for answering later questions. Reply with only the updated "
    "summary, nothing else. Never record whether a file or data is or isn't "
    "attached or available, or that the assistant couldn't see something; that "
    "changes from message to message and must not be carried forward."
)


def update_summary(conversation, user_text, reply_text):
    prompt = (
        f"{SUMMARY_PROMPT}\n\n"
        f"Current summary:\n{conversation.summary or '(none yet)'}\n\n"
        f"New exchange:\nUser: {user_text}\nAssistant: {reply_text}\n\n"
        "Updated summary:"
    )
    message = call_deepseek([{"role": "user", "content": prompt}])
    return message["content"]
