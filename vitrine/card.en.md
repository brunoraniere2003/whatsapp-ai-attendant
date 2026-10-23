AI WhatsApp Attendant for an Online Store, built on the Cloud API

A WhatsApp Cloud API webhook for the questions an online store gets all day: where is my order, send the payment slip again, did my payment go through, how do I return or cancel. It reads messages the way people type on a phone: no accents, typos, slang. When the order number is missing, it asks for it. After two misunderstood messages in a row, or when the customer asks for a person, it hands the chat to a human agent. Every misunderstood message goes to a learning queue.

In 300 simulated conversations, 72.0% were resolved by the bot with the right answer and 7.0% went to a person. Intent accuracy was 86.8% on 121 phrases never used in training. The webhook checks the Meta signature and ignores redelivered events. Logs keep no personal data. An optional Claude layer sees only the messages the local engine rejects. Demo case with fictional data.

Role: Backend and NLP engineer, from specification to evaluation
Skills: Python, FastAPI, WhatsApp Cloud API, NLP, Chatbot, Claude API, Pytest, REST API
