import ast

import pandas as pd
from typing import *
from typing import Literal

from utils.code_dependencies import *

def get_code_definitions(problem_code:str)->str:
    """
    Returns class definitions, usually under a line like:
    # Definition for singly-linked list.
    """
    definition_lines = []
    for line in problem_code.split("\n"):
        if line.startswith("# ") and not line.startswith("# Definition"):
            clean_line = line.removeprefix("# ")
            definition_lines.append(clean_line)
    
    return "\n".join(definition_lines)

def show_all_dataset_definitions(df:pd.DataFrame)->None:
    """
    prints unique class definitions (data structures) from input pd.DataFrame
    Used for checking what it's being used in the Dataset. 
    """
    unique_definitions = set()
    for problem in list(df.iloc):
        if "# Definition" in problem.starter_code:
            # print(p.starter_code)

            definitions = get_code_definitions(problem.starter_code)
            if definitions not in unique_definitions:
                print(definitions)
                unique_definitions.add(definitions)

# Deprecated: Had problems with empty code with only comments.
# def code_runs(code_definitions:str, student_code:str)->bool:
#     """
#     checks wheter the code can run at least
#     requires:
#         - 'from typing import *' since typing structures are used everywhere. 
#         - running dataset definitions before (see above). 
#     """
#     if student_code == "":
#         return False
    
#     # code definitions
#     try: 
#         exec(code_definitions)
#     except Exception as e: raise Warning("Problem runnning code definitions!")
    
#     try: 
#         exec(student_code)
#         return True
#     except Exception as e:
#         Warning(f"Student Code Exception {e}")
#         return False

def code_runs(code_definitions: str, student_code: str) -> bool:
    """
    Checks whether the student's code contains executable statements
    and runs without raising exceptions.
    """

    if not student_code.strip():
        return False

    # Parse AST to detect meaningful code
    try:
        tree = ast.parse(student_code)

        meaningful_nodes = (
            ast.Assign,
            ast.AugAssign,
            ast.AnnAssign,
            ast.FunctionDef,
            ast.AsyncFunctionDef,
            ast.ClassDef,
            ast.Return,
            ast.For,
            ast.While,
            ast.If,
            ast.With,
            ast.Try,
            ast.Expr,  # may include function calls
            ast.Import,
            ast.ImportFrom
        )

        has_code = any(isinstance(node, meaningful_nodes) for node in ast.walk(tree))

        if not has_code:
            print("no code")
            return False

    except SyntaxError:
        return False

    # Run definitions
    try:
        exec(code_definitions)
    except Exception:
        raise Warning("Problem running code definitions!")

    # Run student code
    try:
        exec(student_code)
        return True
    except Exception as e:
        Warning(f"Student Code Exception {e}")
        return False
    
def numeric_test_score(problem, code_definitions:str, student_python_code:str, verbose:Literal[0,1,2]=0):
    asserts = problem.test.split("assert")[1:]
    asserts = [ass.strip() for ass in asserts]
    if verbose>0: print(asserts)

    # code definitions
    try: 
        exec(code_definitions)
    except Exception as e: raise Warning("Problem runnning code definitions!")

    count_passed = 0
    for idx,ass in enumerate(asserts):
        try:
            # replace first occurrence of substring by entry point
            assestent_line_code = ass.replace("candidate", problem.entry_point, 1) 
            # evaluate assert
            exec(student_python_code)
            evaluation_passed = eval(assestent_line_code)
            if (verbose == 2) or (verbose == 1 and not evaluation_passed):
                print(idx, assestent_line_code)
                print(evaluation_passed, '\n')
            if evaluation_passed:
                count_passed += 1
        except: pass
    # return proportion of passed asserts 
    return count_passed / len(asserts)

## NOTE: Deprecated. Attempt to avoid getting stuck using timeout. Didnt work. It seems the issue is not about computational time. 
# from concurrent.futures import ThreadPoolExecutor, TimeoutError
# from tqdm import tqdm

# def numeric_test_score(problem, code_definitions: str, student_python_code: str, verbose: Literal[0,1,2]=0, timeout: int = 5):
#     asserts = problem.test.split("assert")[1:]
#     asserts = [ass.strip() for ass in asserts]
#     if verbose > 0: print(asserts)

#     # code definitions (in shared namespace)
#     namespace = {}
#     try: 
#         exec(code_definitions, namespace)
#     except Exception as e: raise Warning("Problem running code definitions!")

#     count_passed = 0
#     for idx, ass in tqdm(enumerate(asserts)):
#         def run_test():
#             exec(student_python_code, namespace)
#             assestent_line_code = ass.replace("candidate", problem.entry_point, 1)
#             return eval(assestent_line_code, namespace)
        
#         try:
#             with ThreadPoolExecutor() as executor:
#                 evaluation_passed = executor.submit(run_test).result(timeout=timeout)
#                 if (verbose == 2) or (verbose == 1 and not evaluation_passed):
#                     print(idx, assestent_line_code)
#                     print(evaluation_passed, '\n')
#                 if evaluation_passed:
#                     count_passed += 1
#         except TimeoutError:
#             if verbose > 0: print(f"Test {idx} timed out")
#         except: 
#             pass
    
#     return count_passed / len(asserts)