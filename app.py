#!/usr/bin/env python

from uuid import uuid4
import logging
import logging.config

import gradio as gr
from dotenv import load_dotenv
from langgraph.types import RunnableConfig
from pydantic import BaseModel

load_dotenv()

from graph import GraphProcessingState, graph, model

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
FOLLOWUP_QUESTION_NUMBER = 3

async def chat_fn(message, history, input_graph_state, uuid):
    try:
        input_graph_state["user_input"] = message
        input_graph_state["history"] = history
        config = RunnableConfig()
        config["configurable"] = {}
        config["configurable"]["thread_id"] = uuid

        output = ""
        async for msg, metadata in graph.astream(
                    dict(input_graph_state),
                    config=config,
                    stream_mode="messages",
                ):
            # download_website_text is the name of the function defined in graph.py
            if hasattr(msg, "tool_calls") and msg.tool_calls and msg.tool_calls[0]['name'] == "download_website_text":
                # yield {"role": "assistant", "content": "Downloading website text..."}
                yield "Downloading website text...", gr.skip(), False
            # if msg.additional_kwargs['tool_calls'] and msg.additional_kwargs['tool_calls'][0]== "download_website_text":
            # print("output: ", msg, metadata)
            # assistant_node is the name we defined in the langraph graph
            if metadata['langgraph_node'] == "assistant_node" and msg.content:
                output += msg.content
                yield output, gr.skip(), False
        # Trigger for asking follow up questions
        final_state = graph.get_state(config).values
        yield output, final_state, True
    except Exception:
        logger.exception("Exception occurred")
        user_error_message = "There was an error processing your request. Please try again."
        yield user_error_message, gr.skip(), False

def clear():
    return GraphProcessingState(), uuid4()

class FollowupQuestions(BaseModel):
    questions: list[str]

async def change_buttons(end_of_chat_response, messages):
    if not end_of_chat_response or not messages:
        return [gr.skip() for _ in range(FOLLOWUP_QUESTION_NUMBER)]
    if messages[-1]["role"] == "assistant":
        follow_up_questions: FollowupQuestions = await model.with_structured_output(FollowupQuestions).ainvoke([
            ("system", f"suggest {FOLLOWUP_QUESTION_NUMBER} followup questions"),
            *messages,
        ])
        if len(follow_up_questions.questions) != FOLLOWUP_QUESTION_NUMBER:
            raise ValueError("Invalid value of followup questions")
        buttons = []
        for i in range(FOLLOWUP_QUESTION_NUMBER):
            buttons.append(
                gr.Button(follow_up_questions.questions[i], visible=True, elem_classes="chat-tab"),
            )
        return buttons
    else:
        return [gr.skip() for _ in range(FOLLOWUP_QUESTION_NUMBER)]

CSS = """
footer {visibility: hidden}
.followup-question-button {font-size: 12px }
"""

if __name__ == "__main__":
    logger.info("Starting the interface")
    with gr.Blocks(title="Langgraph Template", fill_height=True, css=CSS) as app:
        uuid_state = gr.State(
            uuid4
        )
        gradio_graph_state = gr.State(
            lambda: dict()
        )
        end_of_chat_response_state = gr.State(
            lambda: bool()
        )
        chatbot = gr.Chatbot(
            # avatar_images=(None, "assets/ai-avatar.png"),
            type="messages",
            # placeholder=WELCOME_MESSAGE,/
            scale=1,
        )
        chatbot.clear(fn=clear, outputs=[gradio_graph_state, uuid_state])
        with gr.Row():
            followup_question_buttons = []
            for i in range(FOLLOWUP_QUESTION_NUMBER):
                btn = gr.Button(f"Button {i+1}", visible=False, elem_classes="followup-question-button")
                followup_question_buttons.append(btn)

        chat_interface = gr.ChatInterface(
            chatbot=chatbot,
            fn=chat_fn,
            additional_inputs=[
                gradio_graph_state,
                uuid_state,
            ],
            additional_outputs=[
                gradio_graph_state,
                end_of_chat_response_state
            ],
            type="messages",
            multimodal=False,
        )

        def click_followup_button(btn):
            buttons = [gr.Button(visible=False) for _ in range(len(followup_question_buttons))]
            return btn, *buttons
        for btn in followup_question_buttons:
            btn.click(fn=click_followup_button, inputs=[btn], outputs=[chat_interface.textbox, *followup_question_buttons])

        chatbot.change(fn=change_buttons, inputs=[end_of_chat_response_state, chatbot], outputs=followup_question_buttons, trigger_mode="once")

    app.launch(
        server_name="127.0.0.1",
        server_port=7860,
        # favicon_path="assets/favicon.ico"
    )
