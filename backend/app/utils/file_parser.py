"""
File Parsing Utility
Extracts text from PDF, Markdown, and TXT files
"""

import os
from pathlib import Path
from typing import List, Optional


def _read_text_with_fallback(file_path: str) -> str:
    """
    Read text file with automatic encoding detection on UTF-8 failure.
    
    Multi-stage fallback strategy:
    1. First attempt standard UTF-8 decode
    2. Detect encoding using charset_normalizer
    3. Fallback to chardet
    4. Ultimate fallback: UTF-8 with errors='replace'
    
    Args:
        file_path: Path to file
        
    Returns:
        Decoded text content
    """
    data = Path(file_path).read_bytes()
    
    # Try UTF-8 first
    try:
        return data.decode('utf-8')
    except UnicodeDecodeError:
        pass
    
    # Try charset_normalizer
    encoding = None
    try:
        from charset_normalizer import from_bytes
        best = from_bytes(data).best()
        if best and best.encoding:
            encoding = best.encoding
    except Exception:
        pass
    
    # Fallback to chardet
    if not encoding:
        try:
            import chardet
            result = chardet.detect(data)
            encoding = result.get('encoding') if result else None
        except Exception:
            pass
    
    # Ultimate fallback
    if not encoding:
        encoding = 'utf-8'
    
    return data.decode(encoding, errors='replace')


class FileParser:
    """File Parser"""
    
    SUPPORTED_EXTENSIONS = {'.pdf', '.md', '.markdown', '.txt'}
    
    @classmethod
    def is_supported(cls, file_path: str) -> bool:
        """
        Check if file format is supported
        
        Args:
            file_path: Path to file
            
        Returns:
            True if supported, False otherwise
        """
        suffix = Path(file_path).suffix.lower()
        return suffix in cls.SUPPORTED_EXTENSIONS
    
    @classmethod
    def extract_text(cls, file_path: str) -> str:
        """
        Extract text from file
        
        Args:
            file_path: Path to file
            
        Returns:
            Extracted text content
        """
        path = Path(file_path)
        
        if not path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")
        
        suffix = path.suffix.lower()
        
        if suffix not in cls.SUPPORTED_EXTENSIONS:
            raise ValueError(f"Unsupported file format: {suffix}")
        
        if suffix == '.pdf':
            return cls._extract_from_pdf(file_path)
        elif suffix in {'.md', '.markdown'}:
            return cls._extract_from_md(file_path)
        elif suffix == '.txt':
            return cls._extract_from_txt(file_path)
        
        raise ValueError(f"Unable to process file format: {suffix}")
    
    @staticmethod
    def _extract_from_pdf(file_path: str) -> str:
        """Extract text from PDF"""
        try:
            import fitz  # PyMuPDF
        except ImportError:
            raise ImportError("PyMuPDF required: pip install PyMuPDF")
        
        text_parts = []
        with fitz.open(file_path) as doc:
            for page in doc:
                text = page.get_text()
                if text.strip():
                    text_parts.append(text)
        
        return "\n\n".join(text_parts)
    
    @staticmethod
    def _extract_from_md(file_path: str) -> str:
        """Extract text from Markdown with auto encoding detection"""
        return _read_text_with_fallback(file_path)
    
    @staticmethod
    def _extract_from_txt(file_path: str) -> str:
        """Extract text from TXT with auto encoding detection"""
        return _read_text_with_fallback(file_path)
    
    @classmethod
    def extract_from_multiple(cls, file_paths: List[str]) -> str:
        """
        Extract text from multiple files and merge
        
        Args:
            file_paths: List of file paths
            
        Returns:
            Combined text
        """
        all_texts = []
        
        for i, file_path in enumerate(file_paths, 1):
            try:
                text = cls.extract_text(file_path)
                filename = Path(file_path).name
                all_texts.append(f"=== Document {i}: {filename} ===\n{text}")
            except Exception as e:
                all_texts.append(f"=== Document {i}: {file_path} (Extraction failed: {str(e)}) ===")
        
        return "\n\n".join(all_texts)


def split_text_into_chunks(
    text: str, 
    chunk_size: int = 500, 
    overlap: int = 50
) -> List[str]:
    """
    Split text into smaller chunks
    
    Args:
        text: Original text
        chunk_size: Characters per chunk
        overlap: Character overlap between chunks
        
    Returns:
        List of text chunks
    """
    if len(text) <= chunk_size:
        return [text] if text.strip() else []
    
    chunks = []
    start = 0
    
    while start < len(text):
        end = start + chunk_size
        
        # Attempt to split at sentence boundaries
        if end < len(text):
            for sep in ['.\n', '!\n', '?\n', '\n\n', '. ', '! ', '? ', '; ']:
                last_sep = text[start:end].rfind(sep)
                if last_sep != -1 and last_sep > chunk_size * 0.3:
                    end = start + last_sep + len(sep)
                    break
        
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        
        # Start next chunk from overlap
        start = end - overlap if end < len(text) else len(text)
    
    return chunks
