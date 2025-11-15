# scorecard
Strategic Scorecard

## Configuration

### OpenAI API Key

The AI analysis features require an OpenAI API key. You can configure it in two ways:

#### Option 1: Streamlit Secrets (Recommended for Streamlit Cloud)

Create a `.streamlit/secrets.toml` file in your project root:

```toml
OPENAI_API_KEY = "sk-your-api-key-here"
```

#### Option 2: Environment Variable

Set the environment variable before running the app:

```bash
export OPENAI_API_KEY="sk-your-api-key-here"
streamlit run app.py
```

The application will first try to read from Streamlit secrets, then fall back to the environment variable if not found.

### Custom LLM Providers

The `ai_utils.py` module provides a pluggable interface for using alternative LLM providers. By default, it uses OpenAI, but you can provide your own implementation:

```python
from ai_utils import interpret_scorecard

def my_custom_llm(prompt, model, temperature, max_tokens, system_prompt, **kwargs):
    # Your custom LLM logic here
    # Return the response as a string
    return response_text

# Use your custom LLM
result = interpret_scorecard(
    meta=meta,
    questions_df=questions_df,
    responses=responses,
    llm_call_fn=my_custom_llm
)
```
