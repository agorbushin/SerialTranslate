#!/usr/bin/env python3
"""
API Health Check Module
Tests OpenAI and OpenSubtitles APIs to detect quota, billing, and rate limit issues.
"""

import asyncio
from typing import Dict, Optional, Tuple
from openai import OpenAI, AsyncOpenAI
from download_subtitles import OpenSubtitlesDownloader
import os


class APIHealthChecker:
    """Check health of APIs and detect specific failure reasons."""
    
    def __init__(self, openai_api_key: Optional[str] = None, opensubtitles_api_key: Optional[str] = None):
        """Initialize API health checker.
        
        Args:
            openai_api_key: OpenAI API key (optional, will try to get from env/config)
            opensubtitles_api_key: OpenSubtitles API key (optional, will use default)
        """
        from env_config import get_openai_api_key, get_opensubtitles_api_key

        self.openai_api_key = openai_api_key or get_openai_api_key() or None
        self.opensubtitles_api_key = opensubtitles_api_key or get_opensubtitles_api_key() or None
    
    def check_openai_error(self, error: Exception) -> Dict[str, any]:
        """Check if OpenAI error is due to quota/billing/rate limits.
        
        Args:
            error: Exception from OpenAI API call
            
        Returns:
            Dict with:
                - is_api_issue: bool - True if API-related (quota/billing/rate limit)
                - error_type: str - Type of error (quota, billing, rate_limit, other)
                - message: str - Human-readable error message
                - can_retry: bool - Whether retrying might help
        """
        error_str = str(error).lower()
        error_repr = repr(error).lower()
        
        # Check for quota/billing errors
        quota_keywords = ['quota', 'insufficient_quota', 'billing', 'payment', 'credit', 'exceeded']
        if any(keyword in error_str or keyword in error_repr for keyword in quota_keywords):
            return {
                'is_api_issue': True,
                'error_type': 'quota',
                'message': 'OpenAI API quota exceeded or billing issue. Please check your OpenAI account billing.',
                'can_retry': False,
                'action_required': 'Check billing at https://platform.openai.com/account/billing'
            }
        
        # Check for rate limit errors
        rate_limit_keywords = ['rate limit', 'rate_limit', 'too many requests', '429']
        if any(keyword in error_str or keyword in error_repr for keyword in rate_limit_keywords):
            return {
                'is_api_issue': True,
                'error_type': 'rate_limit',
                'message': 'OpenAI API rate limit exceeded. Please wait before retrying.',
                'can_retry': True,
                'retry_after': 60  # Wait 60 seconds
            }
        
        # Check for authentication errors
        auth_keywords = ['invalid', 'unauthorized', '401', '403', 'authentication', 'api key']
        if any(keyword in error_str or keyword in error_repr for keyword in auth_keywords):
            return {
                'is_api_issue': True,
                'error_type': 'authentication',
                'message': 'OpenAI API authentication failed. Please check your API key.',
                'can_retry': False,
                'action_required': 'Verify API key is correct'
            }
        
        # Other errors
        return {
            'is_api_issue': False,
            'error_type': 'other',
            'message': f'OpenAI API error: {str(error)}',
            'can_retry': True
        }
    
    async def test_openai_api(self) -> Tuple[bool, Optional[str], Optional[Dict]]:
        """Test OpenAI API with a simple call.
        
        Returns:
            Tuple of (success: bool, error_message: Optional[str], error_details: Optional[Dict])
        """
        if not self.openai_api_key:
            return False, "No OpenAI API key provided", None
        
        try:
            # Use AsyncOpenAI for async test
            client = AsyncOpenAI(api_key=self.openai_api_key)
            
            # Simple test: ask for a single word translation (should always work if API is functional)
            response = await asyncio.wait_for(
                client.chat.completions.create(
                    model="gpt-4o-mini",  # Use cheaper model for test
                    messages=[
                        {"role": "system", "content": "You are a helpful translator."},
                        {"role": "user", "content": "Translate the word 'hello' to Russian. Return only the translation, nothing else."}
                    ],
                    temperature=0.0,
                    max_tokens=10
                ),
                timeout=10.0
            )
            
            if response and response.choices and response.choices[0].message:
                result = response.choices[0].message.content.strip()
                if result and len(result) > 0:
                    await client.close()
                    return True, None, None
                else:
                    await client.close()
                    return False, "OpenAI API returned empty response", None
            else:
                await client.close()
                return False, "OpenAI API returned invalid response structure", None
                
        except asyncio.TimeoutError:
            return False, "OpenAI API test timed out", {
                'is_api_issue': True,
                'error_type': 'timeout',
                'message': 'OpenAI API is not responding (timeout)',
                'can_retry': True
            }
        except Exception as e:
            error_details = self.check_openai_error(e)
            return False, str(e), error_details
    
    def test_opensubtitles_api(self) -> Tuple[bool, Optional[str], Optional[Dict]]:
        """Test OpenSubtitles API with a simple search.
        
        Returns:
            Tuple of (success: bool, error_message: Optional[str], error_details: Optional[Dict])
        """
        try:
            downloader = OpenSubtitlesDownloader(api_key=self.opensubtitles_api_key)
            
            # Simple test: search for a very popular series (should always return results)
            results = downloader.search_subtitles(
                query="Friends",
                languages=["en"],
                season_number=1,
                episode_number=1
            )
            
            if results and len(results) > 0:
                return True, None, None
            else:
                return False, "OpenSubtitles API returned no results for test query", {
                    'is_api_issue': True,
                    'error_type': 'no_results',
                    'message': 'OpenSubtitles API is not returning results',
                    'can_retry': True
                }
                
        except Exception as e:
            error_str = str(e).lower()
            
            # Check for rate limit
            if 'rate limit' in error_str or '429' in error_str or 'too many' in error_str:
                return False, str(e), {
                    'is_api_issue': True,
                    'error_type': 'rate_limit',
                    'message': 'OpenSubtitles API rate limit exceeded',
                    'can_retry': True,
                    'retry_after': 60
                }
            
            # Check for authentication
            if 'unauthorized' in error_str or '401' in error_str or '403' in error_str or 'invalid' in error_str:
                return False, str(e), {
                    'is_api_issue': True,
                    'error_type': 'authentication',
                    'message': 'OpenSubtitles API authentication failed',
                    'can_retry': False,
                    'action_required': 'Check API key'
                }
            
            # Other errors
            return False, str(e), {
                'is_api_issue': False,
                'error_type': 'other',
                'message': f'OpenSubtitles API error: {str(e)}',
                'can_retry': True
            }
    
    async def check_all_apis(self) -> Dict[str, any]:
        """Check health of all APIs.
        
        Returns:
            Dict with health status for each API:
            {
                'openai': {
                    'healthy': bool,
                    'error': Optional[str],
                    'error_details': Optional[Dict]
                },
                'opensubtitles': {
                    'healthy': bool,
                    'error': Optional[str],
                    'error_details': Optional[Dict]
                },
                'all_healthy': bool
            }
        """
        results = {
            'openai': {'healthy': False, 'error': None, 'error_details': None},
            'opensubtitles': {'healthy': False, 'error': None, 'error_details': None},
            'all_healthy': False
        }
        
        # Test OpenAI
        openai_success, openai_error, openai_details = await self.test_openai_api()
        results['openai'] = {
            'healthy': openai_success,
            'error': openai_error,
            'error_details': openai_details
        }
        
        # Test OpenSubtitles
        opensubtitles_success, opensubtitles_error, opensubtitles_details = self.test_opensubtitles_api()
        results['opensubtitles'] = {
            'healthy': opensubtitles_success,
            'error': opensubtitles_error,
            'error_details': opensubtitles_details
        }
        
        results['all_healthy'] = openai_success and opensubtitles_success
        
        return results
    
    def format_health_report(self, health_results: Dict) -> str:
        """Format health check results as a human-readable message.
        
        Args:
            health_results: Results from check_all_apis()
            
        Returns:
            Formatted message string
        """
        lines = ["🔍 **API Health Check Results:**\n"]
        
        # OpenAI status
        openai_status = health_results['openai']
        if openai_status['healthy']:
            lines.append("✅ **OpenAI API**: Working")
        else:
            lines.append("❌ **OpenAI API**: Not working")
            if openai_status['error']:
                lines.append(f"   Error: {openai_status['error']}")
            if openai_status['error_details']:
                details = openai_status['error_details']
                lines.append(f"   Type: {details.get('error_type', 'unknown')}")
                if details.get('action_required'):
                    lines.append(f"   Action: {details['action_required']}")
        
        lines.append("")
        
        # OpenSubtitles status
        opensubtitles_status = health_results['opensubtitles']
        if opensubtitles_status['healthy']:
            lines.append("✅ **OpenSubtitles API**: Working")
        else:
            lines.append("❌ **OpenSubtitles API**: Not working")
            if opensubtitles_status['error']:
                lines.append(f"   Error: {opensubtitles_status['error']}")
            if opensubtitles_status['error_details']:
                details = opensubtitles_status['error_details']
                lines.append(f"   Type: {details.get('error_type', 'unknown')}")
                if details.get('action_required'):
                    lines.append(f"   Action: {details['action_required']}")
        
        return "\n".join(lines)


async def quick_openai_test(api_key: str) -> Tuple[bool, Optional[str]]:
    """Quick test of OpenAI API (for use before operations).
    
    Args:
        api_key: OpenAI API key
        
    Returns:
        Tuple of (success: bool, error_message: Optional[str])
    """
    checker = APIHealthChecker(openai_api_key=api_key)
    success, error, _ = await checker.test_openai_api()
    return success, error


def quick_opensubtitles_test(api_key: Optional[str] = None) -> Tuple[bool, Optional[str]]:
    """Quick test of OpenSubtitles API (for use before operations).
    
    Args:
        api_key: OpenSubtitles API key (optional)
        
    Returns:
        Tuple of (success: bool, error_message: Optional[str])
    """
    checker = APIHealthChecker(opensubtitles_api_key=api_key)
    success, error, _ = checker.test_opensubtitles_api()
    return success, error


if __name__ == '__main__':
    """Test the API health checker."""
    import sys
    
    # Get API keys from environment or config
    openai_key = os.environ.get('OPENAI_API_KEY')
    if not openai_key:
        # Try to get from telegram_bot.py
        try:
            with open('telegram_bot.py', 'r') as f:
                for line in f:
                    if 'OPENAI_API_KEY' in line and '=' in line:
                        openai_key = line.split('"')[1] if '"' in line else line.split("'")[1]
                        break
        except:
            pass
    
    checker = APIHealthChecker(openai_api_key=openai_key)
    
    async def main():
        print("Testing APIs...")
        results = await checker.check_all_apis()
        print("\n" + checker.format_health_report(results))
        
        if not results['all_healthy']:
            sys.exit(1)
    
    asyncio.run(main())
