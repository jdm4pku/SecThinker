"""End-to-end CLI, retaining the frozen generation implementation."""
import argparse,sys
from pathlib import Path
from . import core
def main():
 if len(sys.argv)>1 and sys.argv[1]=="run":
  parser=argparse.ArgumentParser(add_help=False);parser.add_argument("--output",type=Path,required=True)
  opts,_=parser.parse_known_args(sys.argv[2:])
  sys.argv[1]="generate"
  core.main()
  from .evaluate import evaluate
  evaluate(opts.output.resolve())
 else:core.main()
if __name__=="__main__":main()
