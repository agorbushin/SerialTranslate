#!/usr/bin/env python3
"""
Extract words from The Oxford 3000 PDF and save to CSV.
"""

import re
import csv
from pathlib import Path
import PyPDF2


def extract_oxford_words(pdf_path: Path) -> list:
    """Extract words from Oxford 3000 PDF."""
    words = set()
    
    with open(pdf_path, 'rb') as f:
        pdf_reader = PyPDF2.PdfReader(f)
        
        for page_num, page in enumerate(pdf_reader.pages):
            text = page.extract_text()
            
            # Split by lines
            lines = text.split('\n')
            
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                
                # Skip header/footer lines
                if 'Oxford' in line or '©' in line or line.startswith('/'):
                    continue
                
                # Pattern: word, part_of_speech level
                # Examples:
                # "a, an indefinite article  A1"
                # "abandon v.  B2"
                # "ability n. A2"
                
                # Extract the first word before comma or space
                # Handle cases like "a, an" - take first word
                match = re.match(r'^([a-z]+(?:\s+[a-z]+)?)', line.lower())
                if match:
                    word_part = match.group(1).strip()
                    # If there's a comma, take the part before comma
                    if ',' in word_part:
                        word = word_part.split(',')[0].strip()
                    else:
                        word = word_part.split()[0].strip()
                    
                    # Clean up - remove any trailing punctuation
                    word = re.sub(r'[^\w]', '', word)
                    
                    if word and len(word) >= 2:  # At least 2 characters
                        words.add(word)
    
    return sorted(list(words))


def main():
    pdf_path = Path('Frequency list/English/The_Oxford_3000.pdf')
    output_path = Path('Frequency list/English/oxford_3000.csv')
    
    print(f"Extracting words from {pdf_path}...")
    words = extract_oxford_words(pdf_path)
    
    print(f"Extracted {len(words)} unique words")
    
    # Save to CSV
    with open(output_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['word'])  # Header
        for word in words:
            writer.writerow([word])
    
    print(f"Saved to {output_path}")
    
    # Show sample
    print(f"\nSample words (first 20):")
    for word in words[:20]:
        print(f"  {word}")


if __name__ == '__main__':
    main()
