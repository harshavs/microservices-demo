# Copyright 2024 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import os
import grpc
import json
from adk.tools import Tool
from langchain_core.messages import HumanMessage
from langchain_google_genai import ChatGoogleGenerativeAI

# Import the generated protobuf files
# Note: We will need to ensure these are generated and available
import gen_protos.demo_pb2 as demo_pb2
import gen_protos.demo_pb2_grpc as demo_pb2_grpc

# --- Tool for Store Policies ---
class StorePolicyTool(Tool):
    def __init__(self):
        super().__init__(
            name="get_store_policy",
            description="Use this tool to get information about store policies, such as return policy, shipping times, and international shipping.",
        )

    def __call__(self, query: str) -> str:
        with open("policies.json", "r") as f:
            policies = json.load(f)

        # For simplicity, this tool will return all policies.
        # A more advanced implementation could use an LLM or semantic search
        # to find the most relevant policy.
        return json.dumps(policies)

# --- Tool for Order Status ---
class OrderStatusTool(Tool):
    def __init__(self):
        super().__init__(
            name="get_order_status",
            description="Use this tool to get the status of a user's order. You will need the order ID.",
        )
        self.checkout_service_addr = os.environ.get("CHECKOUT_SERVICE_ADDR")

    def __call__(self, order_id: str) -> str:
        if not self.checkout_service_addr:
            return "Error: CHECKOUT_SERVICE_ADDR environment variable not set."

        try:
            with grpc.insecure_channel(self.checkout_service_addr) as channel:
                stub = demo_pb2_grpc.CheckoutServiceStub(channel)
                request = demo_pb2.GetOrderRequest(order_id=order_id)
                response = stub.GetOrder(request)
                return response.to_json()
        except grpc.RpcError as e:
            if e.code() == grpc.StatusCode.NOT_FOUND:
                return f"Order with ID '{order_id}' not found."
            return f"An error occurred while fetching the order status: {e.details()}"

# --- Tool for Adding to Cart ---
class AddToCartTool(Tool):
    def __init__(self):
        super().__init__(
            name="add_to_cart",
            description="Use this tool to add a product to the user's shopping cart. You will need the user's session ID, the product ID, and the quantity.",
        )
        self.cart_service_addr = os.environ.get("CART_SERVICE_ADDR")

    def __call__(self, session_id: str, product_id: str, quantity: int) -> str:
        if not self.cart_service_addr:
            return "Error: CART_SERVICE_ADDR environment variable not set."

        try:
            with grpc.insecure_channel(self.cart_service_addr) as channel:
                stub = demo_pb2_grpc.CartServiceStub(channel)
                request = demo_pb2.AddItemRequest(
                    user_id=session_id,
                    item=demo_pb2.CartItem(product_id=product_id, quantity=quantity),
                )
                stub.AddItem(request)
                return f"Successfully added {quantity} of product {product_id} to the cart."
        except grpc.RpcError as e:
            return f"An error occurred while adding the item to the cart: {e.details()}"

# --- Tool for Product Recommendations (RAG) ---
class ProductTool(Tool):
    def __init__(self, vector_store):
        super().__init__(
            name="get_product_recommendations",
            description="Use this tool to get product recommendations based on a user's request and an image of a room. You will need the user's prompt and the image URL.",
        )
        self.vector_store = vector_store

    def __call__(self, prompt: str, image_url: str) -> str:
        # Step 1 – Get a room description from Gemini-vision-pro
        llm_vision = ChatGoogleGenerativeAI(model="gemini-1.5-flash")
        message = HumanMessage(
            content=[
                {
                    "type": "text",
                    "text": "You are a professional interior designer, give me a detailed decsription of the style of the room in this image",
                },
                {"type": "image_url", "image_url": image_url},
            ]
        )
        response = llm_vision.invoke([message])
        description_response = response.content

        # Step 2 – Similarity search with the description & user prompt
        vector_search_prompt = f"This is the user's request: {prompt} Find the most relevant items for that prompt, while matching style of the room described here: {description_response}"
        docs = self.vector_store.similarity_search(vector_search_prompt)

        #Prepare relevant documents for inclusion in final prompt
        relevant_docs = ""
        for doc in docs:
            doc_details = doc.to_json()
            relevant_docs += str(doc_details) + ", "

        # Step 3 – Tie it all together by augmenting our call to Gemini-pro
        llm = ChatGoogleGenerativeAI(model="gemini-1.5-flash")
        design_prompt = (
            f" You are an interior designer that works for Online Boutique. You are tasked with providing recommendations to a customer on what they should add to a given room from our catalog. This is the description of the room: \n"
            f"{description_response} Here are a list of products that are relevant to it: {relevant_docs} Specifically, this is what the customer has asked for, see if you can accommodate it: {prompt} Start by repeating a brief description of the room's design to the customer, then provide your recommendations. Do your best to pick the most relevant item out of the list of products provided, but if none of them seem relevant, then say that instead of inventing a new product. At the end of the response, add a list of the IDs of the relevant products in the following format for the top 3 results: [<first product ID>], [<second product ID>], [<third product ID>] "
        )
        design_response = llm.invoke(design_prompt)

        return design_response.content
