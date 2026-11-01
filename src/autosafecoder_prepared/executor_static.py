import subprocess
import re
import json
import tempfile
import os 
from enum import Enum

from utils import call_chatgpt_analyze_static_security

class FResult(Enum):
    SAFE = 1  # validation returns okay
    FAILURE = 2  # validation contains error (something wrong with validation)
    ERROR = 3  # validation returns a potential error (look into)
    LLM_WEAKNESS = (
        4  # the generated input is ill-formed due to the weakness of the language model
    )
    TIMED_OUT = 10  # timed out, can be okay in certain targets

def extract_function_name(code):
        # Extract the function name from the code using regex
        match = re.search(r'def (\w+)\s*\(', code)
        if match:
            return match.group(1)
        raise ValueError("Function name could not be extracted from the code.")

def remove_json_prefix(input_str):
    # Check if the input string starts with "json\n"
    if input_str.startswith("json\n"):
        # Remove the prefix and return the remaining string
        return input_str[len("json\n"):]
    return input_str


class ExecutorStaticAgent:
    def __init__(self,entry):
        self.entry = entry


    def execute_static_analysis(self,code):
        # Bandit analyzes Python syntax; process/report errors are never SAFE.
        import sys
        path=None
        try:
            with tempfile.NamedTemporaryFile(delete=False,suffix='.py') as f:
                f.write(code.encode('utf-8'));path=f.name
            result=subprocess.run([sys.executable,'-m','bandit','-r',path,'-f','json'],capture_output=True,text=True,timeout=6)
            if result.returncode not in (0,1):
                return FResult.FAILURE,'analysis_error',result.stderr
            report=json.loads(result.stdout)
            if report.get('errors'):
                return FResult.FAILURE,'analysis_error',json.dumps(report['errors'])
            findings=report.get('results')
            if not isinstance(findings,list):
                return FResult.FAILURE,'invalid_report','Missing Bandit results'
            if findings:
                first=findings[0]
                return FResult.ERROR,'CWE-'+str(first.get('issue_cwe',{}).get('id','unknown')),first.get('issue_text','')
            if result.returncode!=0:
                return FResult.FAILURE,'analysis_error','Bandit failed without findings'
            return FResult.SAFE,'0',''
        except subprocess.TimeoutExpired:
            return FResult.TIMED_OUT,'timeout','Bandit timeout'
        except (OSError,ValueError,TypeError) as e:
            return FResult.FAILURE,'analysis_error',str(e)
        finally:
            if path and os.path.exists(path):os.remove(path)

    def execute_static_analysis_gpt(self,code):

        response = call_chatgpt_analyze_static_security(code)
        if ('no vulnerabilities detected'.lower() in response.lower()):
            return FResult.SAFE, "No CWE"
        else:
            return FResult.ERROR, response

    