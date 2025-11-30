import json
import re
import asyncio
from pathlib import Path
from urllib.parse import quote
from typing import Optional, Union

import aiohttp
from bs4 import BeautifulSoup
from crawl4ai import AsyncWebCrawler

from .config import settings


DEFAULT_LANGUAGE = settings.default_language


class AppStoreScraper:
    def __init__(self, output_dir: Optional[Union[str, Path]] = None):
        target_dir = Path(output_dir).expanduser() if output_dir else settings.screenshot_output_dir
        self.output_dir = target_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
    
    async def download_image(self, url: str, filepath: Path) -> bool:
        """Download image from URL"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status == 200:
                        filepath.parent.mkdir(parents=True, exist_ok=True)
                        content = await resp.read()
                        if content:
                            with open(filepath, 'wb') as f:
                                f.write(content)
                            print(f"  ✓ Downloaded: {filepath.name}")
                            return True
                    else:
                        print(f"  ✗ HTTP {resp.status}: {url[:50]}...")
        except Exception as e:
            print(f"  ✗ Error: {e}")
        return False
    
    async def get_app_images(
        self,
        app_url: str,
        app_name: str = "app",
        device_type: str = "iphone",
        language: Optional[str] = DEFAULT_LANGUAGE,
        group_name: Optional[str] = None
    ) -> list:
        """Extract images from app store page, filtered by device type"""
        
        # Device type'a göre URL'ye platform parametresi ekle
        fetch_url = app_url
        if device_type.lower() != "all":
            separator = "&" if "?" in app_url else "?"
            fetch_url = f"{app_url}{separator}platform={device_type}"
        
        headers = None
        lang = DEFAULT_LANGUAGE if language is None else language
        if lang:
            locale = lang.replace("_", "-")
            headers = {"Accept-Language": locale}
        
        async with AsyncWebCrawler() as crawler:
            result = await crawler.arun(
                url=fetch_url,
                bypass_cache=True,
                wait_until="networkidle",
                headers=headers
            )
            
            if not result.success:
                print(f"Failed to crawl {app_url}")
                return []
            
            soup = BeautifulSoup(result.html, 'html.parser')
            image_urls = []
            
            # Tüm picture tag'larını bul
            for picture in soup.find_all('picture'):
                picture_class_str = ' '.join(picture.get('class', [])) if picture.get('class') else ''
                
                # Device filtering - class kontrolü
                should_include = False
                is_screenshot = 'screenshot' in picture_class_str
                
                if not is_screenshot:
                    continue
                
                if device_type.lower() == "all":
                    should_include = True
                elif device_type.lower() == "iphone" and "screenshot-platform-iphone" in picture_class_str:
                    should_include = True
                elif device_type.lower() == "ipad" and "screenshot-platform-ipad" in picture_class_str:
                    should_include = True
                elif device_type.lower() == "appletv" and "screenshot-platform-appleTV" in picture_class_str:
                    should_include = True
                
                # Eğer belirli device type seçildiyse ve bulunamadıysa, en azından screenshot'ları al
                if not should_include and device_type.lower() != "all":
                    should_include = is_screenshot
                
                if should_include:
                    # Source tag'larından en yüksek resolution'ı bul
                    highest_res = 0
                    best_url = None
                    
                    for source in picture.find_all('source'):
                        srcset = source.get('srcset', '')
                        
                        # Srcset'ten tüm URL'leri ve resolution'larını çıkar
                        urls_with_res = re.findall(r'(https://[^\s]+)\s+(\d+)w', srcset)
                        
                        for url, width in urls_with_res:
                            width_int = int(width)
                            # JPG formatını tercih et
                            if width_int > highest_res and ('.jpg' in url or '.webp' in url):
                                highest_res = width_int
                                best_url = url
                    
                    if best_url:
                        # webp'i jpg'ye çevir
                        best_url = best_url.replace('.webp', '.jpg')
                        if best_url not in image_urls:
                            image_urls.append(best_url)
            
            print(f"Found {len(image_urls)} images for {app_name} ({device_type})")
            
            # Store image URLs
            downloaded = []
            for idx, img_url in enumerate(image_urls):
                try:
                    base_dir = self.output_dir / group_name if group_name else self.output_dir
                    app_dir = base_dir / app_name
                    app_dir.mkdir(parents=True, exist_ok=True)
                    
                    downloaded.append({
                        "url": img_url,
                        "path": str(app_dir / f"screenshot_{idx}.jpg"),
                        "index": idx
                    })
                    print(f"Found image {idx + 1}: {img_url[:60]}...")
                except Exception as e:
                    print(f"Error processing image {idx}: {e}")
            
            return downloaded
    
    async def scrape_app(
        self,
        app_id: str,
        app_name: str = "app",
        country: str = "us",
        download: bool = False,
        device_type: str = "iphone",
        language: Optional[str] = DEFAULT_LANGUAGE,
        group_name: Optional[str] = None
    ) -> dict:
        """Main function to scrape app and download images
        
        Args:
            app_id: App Store app ID
            app_name: App name
            country: Country code (e.g., 'us', 'tr')
            download: Whether to download images
            device_type: Filter by device ('iphone', 'ipad', 'appletv', 'all')
            language: Dil parametresi (örn. 'en', 'tr-tr')
            group_name: Çıktı klasörü için isteğe bağlı grup adı
        """
        lang = DEFAULT_LANGUAGE if language is None else language
        base_url = f"https://apps.apple.com/{country}/app/{quote(app_name)}/id{app_id}"
        if lang:
            separator = "&" if "?" in base_url else "?"
            app_url = f"{base_url}{separator}l={lang}"
        else:
            app_url = base_url
        
        print(f"Scraping app: {app_name} (ID: {app_id})")
        print(f"URL: {app_url}")
        print(f"Device type: {device_type}")
        if lang:
            print(f"Language: {lang}")
        if group_name:
            print(f"Group: {group_name}")
        
        images = await self.get_app_images(
            app_url,
            app_name,
            device_type,
            lang,
            group_name
        )
        
        if download:
            print(f"\nDownloading {len(images)} images...")
            downloaded_count = 0
            for img in images:
                filepath = Path(img["path"])
                success = await self.download_image(img["url"], filepath)
                if success:
                    print(f"Downloaded: {filepath.name}")
                    downloaded_count += 1
            print(f"  ✓ Downloaded {downloaded_count}/{len(images)} images")
        else:
            downloaded_count = 0

        result = {
            "app_name": app_name,
            "app_id": app_id,
            "app_url": app_url,
            "images_found": len(images),
            "images": images,
            "country": country,
            "device_type": device_type,
            "language": lang,
            "group": group_name,
            "downloaded_count": downloaded_count
        }
        
        return result


async def main():
    scraper = AppStoreScraper(output_dir="app_store_downloads")
    
    result = await scraper.scrape_app(
        app_id="684119875",
        app_name="PDF-Donusturucu",
        country="tr",
        device_type="iphone",
        download=True
    )
    
    print("\n" + "="*50)
    print("Scraping Result:")
    print(json.dumps(result, indent=2))
    print("="*50)


if __name__ == "__main__":
    asyncio.run(main())
