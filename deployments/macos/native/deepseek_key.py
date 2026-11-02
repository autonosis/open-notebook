"""Read the explicitly authorized existing DeepSeek key without executing .zshrc."""
from pathlib import Path
import os,re,shlex

def get_key():
 key=os.environ.get('DEEPSEEK_API_KEY')
 if not key:
  s=Path('/Users/super/.zshrc').read_text()
  matches=re.findall(r'^\s*(?:export\s+)?DEEPSEEK_API_KEY\s*=\s*(.+)$',s,re.M)
  if not matches:raise RuntimeError('DEEPSEEK_API_KEY assignment not found')
  parts=shlex.split(matches[-1],comments=True)
  if len(parts)!=1:raise RuntimeError('Key assignment is not a single literal value')
  key=parts[0]
 if not key.startswith('sk-') or any(x in key for x in ['$','`','\n',' ']):raise RuntimeError('Key is not a supported literal value')
 return key
