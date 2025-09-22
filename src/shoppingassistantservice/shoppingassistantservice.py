#!/usr/bin/python
#
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
import adk
from adk.models import Gemini
from google.cloud import secretmanager_v1
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_google_alloydb_pg import AlloyDBEngine, AlloyDBVectorStore

# Import the tools
from tools import StorePolicyTool, OrderStatusTool, AddToCartTool, ProductTool

# --- Database and Vector Store Initialization ---
PROJECT_ID = os.environ.get("PROJECT_ID")
REGION = os.environ.get("REGION")
ALLOYDB_DATABASE_NAME = os.environ.get("ALLOYDB_DATABASE_NAME")
ALLOYDB_TABLE_NAME = os.environ.get("ALLOYDB_TABLE_NAME")
ALLOYDB_CLUSTER_NAME = os.environ.get("ALLOYDB_CLUSTER_NAME")
ALLOYDB_INSTANCE_NAME = os.environ.get("ALLOYDB_INSTANCE_NAME")
ALLOYDB_SECRET_NAME = os.environ.get("ALLOYDB_SECRET_NAME")

# Initialize the vector store only if the required environment variables are set
vectorstore = None
if all([PROJECT_ID, REGION, ALLOYDB_CLUSTER_NAME, ALLOYDB_INSTANCE_NAME, ALLOYDB_DATABASE_NAME, ALLOYDB_SECRET_NAME, ALLOYDB_TABLE_NAME]):
    secret_manager_client = secretmanager_v1.SecretManagerServiceClient()
    secret_name = secret_manager_client.secret_version_path(project=PROJECT_ID, secret=ALLOYDB_SECRET_NAME, secret_version="latest")
    secret_request = secretmanager_v1.AccessSecretVersionRequest(name=secret_name)
    secret_response = secret_manager_client.access_secret_version(request=secret_request)
    PGPASSWORD = secret_response.payload.data.decode("UTF-8").strip()

    engine = AlloyDBEngine.from_instance(
        project_id=PROJECT_ID,
        region=REGION,
        cluster=ALLOYDB_CLUSTER_NAME,
        instance=ALLOYDB_INSTANCE_NAME,
        database=ALLOYDB_DATABASE_NAME,
        user="postgres",
        password=PGPASSWORD
    )

    vectorstore = AlloyDBVectorStore.create_sync(
        engine=engine,
        table_name=ALLOYDB_TABLE_NAME,
        embedding_service=GoogleGenerativeAIEmbeddings(model="models/embedding-001"),
        id_column="id",
        content_column="description",
        embedding_column="product_embedding",
        metadata_columns=["id", "name", "categories"]
    )

# --- Agent Definition ---
def main():
    # Initialize the tools
    tools = [StorePolicyTool(), OrderStatusTool(), AddToCartTool()]
    if vectorstore:
        tools.append(ProductTool(vector_store=vectorstore))

    # Define the prompt for the agent
    prompt = """You are a helpful shopping assistant for the Online Boutique.
    Your goal is to assist users with their shopping needs, answer their questions, and help them manage their cart.
    You have access to a set of tools to help you with this.

    Here are the tools you can use:
    - get_store_policy: Use this to answer questions about store policies (e.g., returns, shipping).
    - get_order_status: Use this to get the status of a user's order. You will need the order ID.
    - add_to_cart: Use this to add a product to the user's shopping cart. You will need the user's session ID, the product ID, and the quantity.
    - get_product_recommendations: Use this to get product recommendations based on a user's request and an image of a room.

    Always be friendly and helpful. If you can't answer a question, say so politely.
    """

    # Create the agent
    agent = adk.Agent(
        prompt=prompt,
        model=Gemini(model="gemini-1.5-flash"),
        tools=tools,
    )

    # Run the agent as a web server
    # The ADK will handle the HTTP requests and conversational state
    adk.run(agent=agent, port=8080)

if __name__ == "__main__":
    main()
