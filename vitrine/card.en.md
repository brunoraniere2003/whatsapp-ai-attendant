AI WhatsApp Attendant for an Online Store, built on the Cloud API

An online store gets the same questions on WhatsApp all day: where is my order, send the payment slip again, did my payment go through, how do I return or cancel. This Cloud API webhook answers them on its own.

It reads messages typed on a phone (no accents, typos, slang) because the classifier also scores character trigrams. When the order number is missing, it asks for it. After two misunderstood messages in a row, or when the customer asks for a person, the chat goes to a human agent. Every misunderstood message lands in a learning queue.

In 300 simulated conversations, the bot resolved 72.0% with the right answer and handed 7.0% to a person. I counted confident wrong answers as failures. Intent accuracy was 86.8% on 121 phrases never used in training. The webhook checks the Meta HMAC signature and ignores redelivered events. Logs keep no personal data. An optional Claude layer only sees what the local engine rejects.

Demo case with fictional data.

Role: Backend and NLP engineer, from specification to evaluation
Skills: Python, FastAPI, WhatsApp Cloud API, NLP, Chatbot, Claude API, Pytest, REST API
