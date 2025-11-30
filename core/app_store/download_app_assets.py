"""
App Store Asset Downloader - Logo ve Screenshot İndirici

Belirtilen app ID için birden fazla ülkeden:
- App logosu (512x512 veya en yüksek çözünürlük)
- iPhone screenshot'ları

İndirir ve PDF rapor oluşturur.
"""

import asyncio
import json
import re
import unicodedata
from argparse import ArgumentParser, Namespace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

import aiohttp
from bs4 import BeautifulSoup
from crawl4ai import AsyncWebCrawler
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader
from reportlab.lib import colors
from reportlab.platypus import Table, TableStyle
from PIL import Image

from .config import settings


DEFAULT_COUNTRIES = ["us", "tr", "jp", "ca", "gb", "de", "fr"]
DEFAULT_OUTPUT_DIR = Path("app_store_assets")
DEFAULT_LANGUAGE = settings.default_language or "en"

COUNTRY_LANGUAGE_MAP = {
    "us": "en",
    "gb": "en-gb",
    "ie": "en-ie",
    "ca": "en-ca",
    "au": "en-au",
    "nz": "en-nz",
    "sg": "en-sg",
    "in": "en-in",
    "za": "en-za",
    "tr": "tr",
    "de": "de",
    "at": "de-at",
    "ch": "de-ch",
    "fr": "fr",
    "be": "fr-be",
    "it": "it",
    "es": "es",
    "mx": "es-mx",
    "ar": "es-ar",
    "cl": "es-cl",
    "co": "es-co",
    "pe": "es-pe",
    "br": "pt-br",
    "pt": "pt-pt",
    "nl": "nl",
    "se": "sv",
    "no": "no",
    "dk": "da",
    "fi": "fi",
    "pl": "pl",
    "cz": "cs",
    "hu": "hu",
    "gr": "el",
    "ro": "ro",
    "sk": "sk",
    "jp": "ja",
    "kr": "ko",
    "cn": "zh",
    "tw": "zh-hant",
    "hk": "zh-hk",
    "id": "id",
    "my": "ms",
    "th": "th",
    "vn": "vi",
    "ru": "ru",
    "ua": "uk",
    "ae": "ar",
    "sa": "ar",
    "qa": "ar",
    "kw": "ar",
    "il": "he",
}


class AppAssetDownloader:
    """App Store'dan logo ve screenshot indiren sınıf."""
    
    def __init__(self, output_dir: Path):
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def _resolve_language(self, country: str, override: Optional[str]) -> Optional[str]:
        """Ülkeye göre varsayılan dil parametresini döndür."""
        if override:
            return override
        country_code = (country or "").lower()
        return COUNTRY_LANGUAGE_MAP.get(country_code, DEFAULT_LANGUAGE)

    def _extract_slug(self, metadata: Optional[Dict[str, Any]]) -> Optional[str]:
        """trackViewUrl ya da app adından slug üret."""
        if not metadata:
            return None
        track_url = metadata.get("trackViewUrl")
        if track_url:
            match = re.search(r"/app/([^/]+)/id\d+", track_url)
            if match:
                return match.group(1)
        track_name = metadata.get("trackName")
        if not track_name:
            return None
        normalized = unicodedata.normalize("NFKD", track_name)
        ascii_name = normalized.encode("ascii", "ignore").decode("ascii")
        slug = re.sub(r"[^a-z0-9]+", "-", ascii_name.lower()).strip("-")
        return slug or None

    def _build_app_store_url(
        self,
        app_id: str,
        country: str,
        slug: Optional[str],
        language: Optional[str],
        platform: Optional[str] = "iphone",
    ) -> str:
        """Slug ve dil parametrelerini kullanarak App Store URL'i oluştur."""
        country_code = (country or "us").lower()
        base_path = f"https://apps.apple.com/{country_code}/app"
        path_segment = f"/{slug}/id{app_id}" if slug else f"/id{app_id}"
        url = f"{base_path}{path_segment}"
        params = []
        if language:
            params.append(("l", language))
        if platform:
            params.append(("platform", platform))
        if params:
            query = "&".join(f"{key}={quote(str(value))}" for key, value in params)
            url = f"{url}?{query}"
        return url

    def _normalize_image_url(self, url: str) -> str:
        """Apple CDN URL'lerini normalize et."""
        if not url:
            return ""
        normalized = url.strip()
        if normalized.startswith("//"):
            normalized = f"https:{normalized}"
        normalized = normalized.replace(".webp", ".jpg")
        return normalized

    def _parse_srcset(self, srcset: str) -> List[Tuple[float, int, str]]:
        """srcset attribute'ünden (score, order, url) listesi üret."""
        if not srcset:
            return []
        candidates: List[Tuple[float, int, str]] = []
        for order, chunk in enumerate(srcset.split(",")):
            entry = chunk.strip()
            if not entry:
                continue
            parts = entry.split()
            url = parts[0] if parts else ""
            descriptor = parts[1] if len(parts) > 1 else ""
            score = 0.0
            match = re.match(r"(?P<value>\d+(?:\.\d+)?)(?P<unit>[wx])", descriptor)
            if match:
                value = float(match.group("value"))
                unit = match.group("unit")
                score = value if unit == "w" else value * 1000
            normalized_url = self._normalize_image_url(url)
            if normalized_url.startswith("http"):
                candidates.append((score, order, normalized_url))
        return candidates
    
    async def download_file(self, url: str, filepath: Path) -> bool:
        """Dosyayı URL'den indir."""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                    if resp.status == 200:
                        filepath.parent.mkdir(parents=True, exist_ok=True)
                        content = await resp.read()
                        if content:
                            with open(filepath, 'wb') as f:
                                f.write(content)
                            return True
                    else:
                        print(f"  ✗ HTTP {resp.status}: {url[:60]}...")
        except Exception as e:
            print(f"  ✗ Download error: {e}")
        return False
    
    async def get_app_metadata(self, app_id: str, country: str = "us") -> Optional[Dict[str, Any]]:
        """iTunes Search API'den app metadata al (screenshot URL'leri dahil)."""
        url = f"https://itunes.apple.com/lookup?id={app_id}&country={country}&entity=software"
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    if resp.status == 200:
                        data = await resp.json(content_type=None)
                        results = data.get("results", [])
                        if results:
                            return results[0]
                        else:
                            print(f"  ⚠️  {country.upper()}: App bulunamadı (ID geçersiz olabilir)")
                    else:
                        print(f"  ✗ {country.upper()}: iTunes API HTTP {resp.status}")
        except Exception as e:
            print(f"  ✗ {country.upper()}: Metadata error: {e}")
        return None
    
    async def download_logo(
        self,
        app_id: str,
        app_name: str,
        country: str,
        output_subdir: Path,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Optional[Path]:
        """App logosunu indir (iTunes API'den)."""
        metadata = metadata or await self.get_app_metadata(app_id, country)
        if not metadata:
            print(f"  ✗ {country.upper()}: Metadata alınamadı")
            return None
        
        # En yüksek çözünürlüklü artwork URL'ini al
        artwork_url = metadata.get("artworkUrl512") or metadata.get("artworkUrl100") or metadata.get("artworkUrl60")
        
        if not artwork_url:
            print(f"  ✗ {country.upper()}: Logo URL bulunamadı")
            return None
        
        # 512x512 versiyonunu zorla
        artwork_url = re.sub(r'/\d+x\d+bb\.', '/512x512bb.', artwork_url)
        
        logo_path = output_subdir / f"logo_{country}.jpg"
        success = await self.download_file(artwork_url, logo_path)
        
        if success:
            print(f"  ✓ {country.upper()}: Logo indirildi")
            return logo_path
        else:
            print(f"  ✗ {country.upper()}: Logo indirilemedi")
            return None
    
    async def download_screenshots(
        self,
        app_id: str,
        app_name: str,
        country: str,
        language: Optional[str],
        slug: Optional[str],
        output_subdir: Path,
        metadata: Optional[Dict[str, Any]] = None,
        force_scrape: bool = False,
    ) -> List[Path]:
        """iPhone screenshot'larını indir."""

        metadata = metadata or await self.get_app_metadata(app_id, country)

        screenshot_urls: List[str] = []
        if metadata:
            screenshot_urls = metadata.get("screenshotUrls", [])

        if metadata and screenshot_urls and not force_scrape:
            print(f"  🔍 {country.upper()}: iTunes API'den screenshot URL'leri alınıyor...")
            print(f"  ✓ {country.upper()}: iTunes API'den {len(screenshot_urls)} screenshot URL bulundu")

            downloaded_paths = []
            for idx, img_url in enumerate(screenshot_urls):
                screenshot_path = output_subdir / f"screenshot_{idx + 1}.jpg"
                success = await self.download_file(img_url, screenshot_path)
                if success:
                    downloaded_paths.append(screenshot_path)

            if downloaded_paths:
                print(f"  ✓ {country.upper()}: {len(downloaded_paths)}/{len(screenshot_urls)} screenshot indirildi")
                return downloaded_paths

        if force_scrape:
            print(f"  ⚙️ {country.upper()}: iTunes API'den gelen URL'ler kullanılamıyor, scraping ile devam ediliyor...")
        elif metadata and not screenshot_urls:
            print(f"  ⚠️  {country.upper()}: iTunes API'de screenshot URL yok, web scraping deneniyor...")

        # iTunes API'den alınamazsa web scraping yap
        slug_value = slug or self._extract_slug(metadata)
        app_url = self._build_app_store_url(
            app_id,
            country,
            slug_value,
            language,
            platform="iphone",
        )

        headers = None
        if language:
            locale = language.replace("_", "-")
            headers = {"Accept-Language": locale}
        
        try:
            async with AsyncWebCrawler() as crawler:
                result = await crawler.arun(
                    url=app_url,
                    bypass_cache=True,
                    wait_until="networkidle",
                    headers=headers,
                    page_timeout=60000,  # 60 saniye timeout
                    delay_before_return_html=5.0,  # JavaScript'in çalışması için daha uzun bekle
                    js_code=[
                        "window.scrollTo(0, 500);",  # Önce biraz scroll
                        "await new Promise(r => setTimeout(r, 1000));",
                        "window.scrollTo(0, 1000);",  # Daha fazla scroll (lazy loading için)
                        "await new Promise(r => setTimeout(r, 2000));",
                        "window.scrollTo(0, 1500);",  # Screenshot bölgesine kadar
                        "await new Promise(r => setTimeout(r, 2000));",
                    ]
                )
                
                if not result.success:
                    print(f"  ✗ {country.upper()}: Sayfa yüklenemedi")
                    return []
                
                soup = BeautifulSoup(result.html, 'html.parser')
                image_urls = []
                
                # Debug: Sayfa içeriğini kontrol et
                all_pictures = soup.find_all('picture')
                print(f"  🔍 {country.upper()}: {len(all_pictures)} picture elementi bulundu")
                
                # Debug: İlk birkaç picture elementini incele
                if all_pictures and len(all_pictures) > 0:
                    for idx, pic in enumerate(all_pictures[:3]):
                        pic_class = ' '.join(pic.get('class', [])) if pic.get('class') else 'NO_CLASS'
                        sources = pic.find_all('source')
                        print(f"    Picture {idx+1}: class='{pic_class}', sources={len(sources)}")
                        if sources:
                            first_src = sources[0].get('srcset', '')[:100]
                            print(f"      First srcset: {first_src}...")
                
                # Yöntem 1: Tüm picture elementlerinden screenshot URL'lerini al
                print(f"  🔍 {country.upper()}: Tüm source elementleri parse ediliyor...")
                seen_base_urls = set()  # Aynı screenshot'ın farklı formatlarını takip et
                
                for picture in all_pictures:
                    # Sadece JPG source'ları al (webp'yi atla)
                    jpg_sources = [s for s in picture.find_all('source') if 'image/jpeg' in s.get('type', '')]
                    
                    for source in jpg_sources:
                        srcset = source.get('srcset') or source.get('data-srcset', '')
                        if not srcset or 'mzstatic.com' not in srcset:
                            continue
                        
                        # srcset'i parse et
                        candidates = self._parse_srcset(srcset)
                        if not candidates:
                            continue
                        
                        # En yüksek çözünürlüklü URL'i al (600w)
                        candidates.sort(key=lambda x: x[0], reverse=True)
                        score, _, url = candidates[0]
                        
                        # Filtrele: AppIcon, marketing, 1200x630 hariç
                        if any(exclude in url for exclude in ['AppIcon', 'marketing', '1200x630']):
                            continue
                        
                        # Screenshot boyutlarını kontrol et (en az 300x)
                        if re.search(r'/(300x|600x|460x|314x|230x|157x)\d+bb', url):
                            # Base URL'i çıkar (boyut ve format olmadan)
                            base_url = re.sub(r'/\d+x\d+bb.*$', '', url)
                            
                            if base_url not in seen_base_urls:
                                seen_base_urls.add(base_url)
                                image_urls.append(url)
                                print(f"      Found: {url[:80]}...")
                                if len(image_urls) >= 10:
                                    break
                    
                    if len(image_urls) >= 10:
                        break
                
                # Yöntem 2: Eğer hala bulamadıysak, daha gevşek filtre
                if not image_urls:
                    print(f"  🔍 {country.upper()}: Gevşek filtre ile deneniyor...")
                    for picture in all_pictures:
                        for source in picture.find_all('source'):
                            srcset = source.get('srcset', '')
                            # is.mzstatic.com domain'i Apple CDN'i - daha geniş filtre
                            if 'is.mzstatic.com' in srcset:
                                # Herhangi bir iPhone boyutu
                                if any(size in srcset for size in ['1290x', '1242x', '1170x', '1179x', '1284x', '828x', '750x', '640x']):
                                    for _, _, url in self._parse_srcset(srcset):
                                        if url not in image_urls:
                                            image_urls.append(url)
                                            print(f"      Found: {url[:80]}...")
                                            if len(image_urls) >= 10:  # Max 10 screenshot
                                                break
                        if len(image_urls) >= 10:
                            break
                
                # Yöntem 3: img tag'lerinden de dene
                if not image_urls:
                    print(f"  🔍 {country.upper()}: img tag'leri deneniyor...")
                    all_imgs = soup.find_all('img')
                    print(f"      Toplam {len(all_imgs)} img elementi bulundu")
                    
                    for img in all_imgs:
                        img_class = ' '.join(img.get('class', [])) if img.get('class') else ''
                        src = img.get('src', '') or img.get('data-src', '') or img.get('data-lazy-src', '')
                        
                        # Apple CDN'den gelen tüm resimleri kontrol et
                        if src and 'is.mzstatic.com' in src:
                            # Screenshot boyutlarını kontrol et (daha geniş filtre)
                            if any(size in src for size in ['1290x', '1242x', '1170x', '1179x', '1284x', '828x', '750x', '640x']):
                                # Yüksek çözünürlük için URL'i düzenle
                                src = re.sub(r'/\d+x\d+bb\.', '/1290x2796bb.', src)
                                src = src.replace('.webp', '.jpg')
                                if src not in image_urls:
                                    image_urls.append(src)
                                    print(f"      Found img: {src[:80]}...")
                                    if len(image_urls) >= 10:
                                        break
                
                # Yöntem 4: Tüm source elementlerini direkt tara (son çare)
                if not image_urls:
                    print(f"  🔍 {country.upper()}: Tüm source elementleri taranıyor...")
                    all_sources = soup.find_all('source')
                    print(f"      Toplam {len(all_sources)} source elementi bulundu")
                    
                    for source in all_sources:
                        srcset = source.get('srcset') or source.get('data-srcset', '')
                        if 'is.mzstatic.com' in srcset or 'mzstatic.com' in srcset:
                            # srcset'teki tüm URL'leri çıkar
                            for _, _, url in self._parse_srcset(srcset):
                                # iPhone boyutlarını kontrol et
                                if any(size in url for size in ['1290x', '1242x', '1170x', '1179x', '1284x', '828x', '750x']):
                                    if url not in image_urls:
                                        image_urls.append(url)
                                        print(f"      Found source: {url[:80]}...")
                                        if len(image_urls) >= 10:
                                            break
                        if len(image_urls) >= 10:
                            break
                
                # Yöntem 5: HTML içinde tüm mzstatic URL'lerini regex ile bul
                if not image_urls:
                    print(f"  🔍 {country.upper()}: HTML içinde regex ile aranıyor...")
                    # Tüm mzstatic URL'lerini bul (daha iyi pattern - tüm geçerli URL karakterleri)
                    all_mzstatic_urls = re.findall(
                        r'https://[a-zA-Z0-9\-._~:/?#\[\]@!$&()*+,;=%]+mzstatic\.com/[a-zA-Z0-9\-._~:/?#\[\]@!$&()*+,;=%]+',
                        result.html
                    )
                    print(f"      Toplam {len(all_mzstatic_urls)} mzstatic URL bulundu")
                    
                    # Önce screenshot boyutlarına göre filtrele (ÇOK DAHA GENİŞ)
                    screenshot_candidates = []
                    for url in all_mzstatic_urls:
                        # Hariç tutulacaklar
                        if any(exclude in url for exclude in ['1200x630', 'AppIcon-', 'marketing']):
                            continue
                        
                        # /image/thumb/ içeren ve boyut bilgisi olan tüm URL'ler
                        if '/image/thumb/' in url:
                            # Herhangi bir boyut formatı var mı? (örn: 392x696, 1290x2796, vb.)
                            if re.search(r'\d{3,4}x\d{3,4}', url):
                                screenshot_candidates.append(url)
                    
                    print(f"      {len(screenshot_candidates)} screenshot adayı bulundu")
                    
                    # Eğer hala bulamadıysak, daha da gevşet
                    if not screenshot_candidates:
                        print(f"      Filtre gevşetiliyor...")
                        for url in all_mzstatic_urls:
                            if 'AppIcon' not in url and '1200x630' not in url:
                                if '/image/thumb/' in url or '/Purple' in url or '/Features' in url:
                                    if re.search(r'\d{3,4}x\d{3,4}', url):
                                        screenshot_candidates.append(url)
                        print(f"      Gevşek filtre ile {len(screenshot_candidates)} aday bulundu")
                    
                    # Unique URL'leri al ve sırala
                    unique_candidates = list(dict.fromkeys(screenshot_candidates))
                    
                    for url in unique_candidates:
                        # URL'i temizle - sadece geçerli karakterlere kadar al
                        url = url.split('&')[0].split('"')[0].split("'")[0].split(')')[0].split(',')[0]
                        
                        # .webp veya .png'yi .jpg'ye çevir (ama URL'de zaten varsa değiştirme)
                        if url.endswith('.webp'):
                            url = url.replace('.webp', '.jpg')
                        elif url.endswith('.png'):
                            url = url.replace('.png', '.jpg')
                        elif not url.endswith(('.jpg', '.jpeg')):
                            # Eğer uzantı yoksa .jpg ekle
                            url = url + '.jpg'
                        
                        if url not in image_urls:
                            image_urls.append(url)
                            print(f"      Found regex: {url[:80]}...")
                            if len(image_urls) >= 10:
                                break
                
                if not image_urls:
                    metadata_for_fallback = metadata or await self.get_app_metadata(app_id, country)
                    api_screenshots = []
                    if metadata_for_fallback:
                        api_screenshots = metadata_for_fallback.get("screenshotUrls") or []
                    if api_screenshots:
                        image_urls = [self._normalize_image_url(url) for url in api_screenshots[:10]]
                        print(f"  ✓ {country.upper()}: iTunes API üzerinden {len(image_urls)} screenshot bulundu (fallback)")
                
                if not image_urls:
                    print(f"  ✗ {country.upper()}: Screenshot bulunamadı (app mevcut değil veya screenshot yok)")
                    # Debug: Tam HTML'i kaydet
                    debug_file = output_subdir / "debug_html_full.txt"
                    with open(debug_file, 'w', encoding='utf-8') as f:
                        f.write(result.html)
                    print(f"      Debug: Tam HTML kaydedildi ({len(result.html)} karakter): {debug_file}")
                    
                    # Tüm mzstatic URL'lerini de kaydet
                    debug_urls_file = output_subdir / "debug_urls.txt"
                    all_urls = re.findall(r'https://[^\s"\'<>]+mzstatic\.com/[^\s"\'<>]+', result.html)
                    with open(debug_urls_file, 'w', encoding='utf-8') as f:
                        for url in sorted(set(all_urls)):
                            f.write(url + '\n')
                    print(f"      Debug: {len(set(all_urls))} unique URL kaydedildi: {debug_urls_file}")
                    return []
                
                print(f"  ✓ {country.upper()}: {len(image_urls)} screenshot bulundu")
                
                # Screenshot'ları indir
                downloaded_paths = []
                for idx, img_url in enumerate(image_urls):
                    screenshot_path = output_subdir / f"screenshot_{idx + 1}.jpg"
                    success = await self.download_file(img_url, screenshot_path)
                    if success:
                        downloaded_paths.append(screenshot_path)
                
                print(f"  ✓ {country.upper()}: {len(downloaded_paths)}/{len(image_urls)} screenshot indirildi")
                return downloaded_paths
                
        except Exception as e:
            print(f"  ✗ {country.upper()}: Screenshot hatası: {e}")
            return []
    
    async def download_assets_for_country(
        self,
        app_id: str,
        app_name: str,
        country: str,
        language: Optional[str] = None,
        force_scrape: bool = False,
    ) -> Dict[str, Any]:
        """Belirli bir ülke için tüm asset'leri indir."""
        country_code = (country or "us").lower()
        print(f"\n📍 {country_code.upper()} - İndiriliyor...")
        
        country_dir = self.output_dir / app_name / country_code
        country_dir.mkdir(parents=True, exist_ok=True)
        metadata = await self.get_app_metadata(app_id, country_code)
        resolved_language = self._resolve_language(country_code, language)
        if resolved_language and not resolved_language.lower().startswith("en"):
            # Non-English markets frequently require scraping to fetch localized metadata.
            force_scrape = True
        slug = self._extract_slug(metadata)
        
        # Logo indir
        logo_path = await self.download_logo(app_id, app_name, country_code, country_dir, metadata)
        
        # Screenshot'ları indir
        screenshot_paths = await self.download_screenshots(
            app_id,
            app_name,
            country_code,
            resolved_language,
            slug,
            country_dir,
            metadata,
            force_scrape=force_scrape,
        )
        
        # App Store URL'ini oluştur
        app_store_url = self._build_app_store_url(
            app_id,
            country_code,
            slug,
            resolved_language,
            platform=None,
        )
        
        return {
            "country": country_code,
            "language": resolved_language,
            "app_store_url": app_store_url,
            "logo_path": str(logo_path) if logo_path else None,
            "screenshot_paths": [str(p) for p in screenshot_paths],
            "screenshot_count": len(screenshot_paths),
        }
    
    async def download_all_countries(
        self,
        app_id: str,
        app_name: str,
        countries: List[str],
        language_map: Optional[Dict[str, str]] = None
    ) -> List[Dict[str, Any]]:
        """Tüm ülkeler için asset'leri indir."""
        results = []
        normalized_language_map = (
            {key.lower(): value for key, value in language_map.items()}
            if language_map
            else None
        )
        primary_country_code = (countries[0].lower() if countries else "us")
        
        for country in countries:
            country_code = (country or "us").lower()
            language = normalized_language_map.get(country_code) if normalized_language_map else None
            result = await self.download_assets_for_country(
                app_id,
                app_name,
                country_code,
                language,
                force_scrape=country_code != primary_country_code,
            )
            results.append(result)
            
            # Rate limiting
            await asyncio.sleep(2)
        
        return results


def create_pdf_report(
    app_name: str,
    app_id: str,
    results: List[Dict[str, Any]],
    output_path: Path,
    app_info: Optional[Dict[str, Any]] = None
) -> None:
    """İndirilen asset'lerden PDF rapor oluştur."""
    print(f"\n📄 PDF rapor oluşturuluyor...")
    
    # En az bir asset var mı kontrol et
    has_any_asset = any(
        result.get("logo_path") or result.get("screenshot_paths")
        for result in results
    )
    
    if not has_any_asset:
        print(f"  ⚠️  Hiç asset indirilemedi, PDF oluşturulmayacak")
        return
    
    # PDF oluştur (yüksek kalite)
    c = canvas.Canvas(str(output_path), pagesize=landscape(A4))
    c.setPageCompression(1)
    page_width, page_height = landscape(A4)
    
    # === COVER PAGE (Enhanced) ===
    _create_cover_page(c, page_width, page_height, app_name, app_id, results, app_info)
    c.showPage()
    
    # === TABLE OF CONTENTS ===
    _create_table_of_contents(c, page_width, page_height, results)
    c.showPage()
    
    # === LOGO COMPARISON GRID ===
    _create_logo_comparison_grid(c, page_width, page_height, app_name, results)
    c.showPage()
    
    # === SCREENSHOT COMPARISON GRID ===
    _create_screenshot_comparison_grid(c, page_width, page_height, app_name, results)
    c.showPage()
    
    # Her ülke için sayfa
    for result in results:
        country = result["country"].upper()
        logo_path = result.get("logo_path")
        screenshot_paths = result.get("screenshot_paths", [])
        
        c.setFont("Helvetica-Bold", 18)
        c.drawString(50, page_height - 50, f"Country: {country}")
        
        y_position = page_height - 100
        
        # Logo göster
        if logo_path and Path(logo_path).exists():
            try:
                img = Image.open(logo_path)
                img_width, img_height = img.size
                
                # Logo boyutunu ayarla (max 150x150)
                max_size = 150
                scale = min(max_size / img_width, max_size / img_height)
                display_width = img_width * scale
                display_height = img_height * scale
                
                c.drawImage(
                    logo_path,
                    50,
                    y_position - display_height,
                    width=display_width,
                    height=display_height,
                    preserveAspectRatio=True
                )
                
                c.setFont("Helvetica", 10)
                c.drawString(50, y_position - display_height - 15, "App Logo")
                
                y_position -= (display_height + 40)
            except Exception as e:
                print(f"  ⚠️  Logo PDF'e eklenemedi ({country}): {e}")
        
        # Screenshot'ları göster - TÜM screenshot'lar
        if screenshot_paths:
            label_text = f"Screenshots ({len(screenshot_paths)})"
            max_screenshot_height = 250  # Daha büyük boyut
            screenshots_per_row = 3  # Her satırda 3 screenshot

            # İlk etiketi çizmeye yetecek alan yoksa yeni sayfa aç
            if y_position - (max_screenshot_height + 40) < 50:
                c.showPage()
                c.setFont("Helvetica-Bold", 14)
                c.drawString(50, page_height - 30, f"Country: {country} (continued)")
                y_position = page_height - 70

            c.setFont("Helvetica-Bold", 12)
            c.drawString(50, y_position, label_text)
            y_position -= 30
            
            x_position = 50
            
            for idx, screenshot_path in enumerate(screenshot_paths):  # TÜM screenshot'lar
                if not Path(screenshot_path).exists():
                    continue
                
                try:
                    img = Image.open(screenshot_path)
                    img_width, img_height = img.size
                    
                    # Screenshot boyutunu ayarla (daha yüksek kalite)
                    scale = max_screenshot_height / img_height
                    display_width = img_width * scale
                    display_height = img_height * scale
                    
                    # Her 3 screenshot'ta bir yeni satır
                    if idx > 0 and idx % screenshots_per_row == 0:
                        x_position = 50
                        y_position -= (max_screenshot_height + 40)
                    
                    # Satır sonrası sayfada yer kalmadıysa yeni sayfa aç
                    if y_position - display_height < 50:
                        c.showPage()
                        c.setFont("Helvetica-Bold", 14)
                        c.drawString(50, page_height - 30, f"Country: {country} (continued)")
                        y_position = page_height - 70
                        c.setFont("Helvetica-Bold", 12)
                        c.drawString(50, y_position, label_text)
                        y_position -= 30
                        x_position = 50
                    
                    # Yüksek kaliteli render
                    c.drawImage(
                        screenshot_path,
                        x_position,
                        y_position - display_height,
                        width=display_width,
                        height=display_height,
                        preserveAspectRatio=True,
                        mask='auto'  # Daha iyi kalite
                    )
                    
                    x_position += display_width + 20
                    
                except Exception as e:
                    print(f"  ⚠️  Screenshot PDF'e eklenemedi ({country}, #{idx+1}): {e}")
        
        c.showPage()
    
    c.save()
    print(f"✓ PDF rapor kaydedildi: {output_path}")


def _create_cover_page(
    c: canvas.Canvas,
    page_width: float,
    page_height: float,
    app_name: str,
    app_id: str,
    results: List[Dict[str, Any]],
    app_info: Optional[Dict[str, Any]]
) -> None:
    """Enhanced cover page with app metadata and statistics."""
    
    # Title box with gradient-like effect (dark background)
    c.setFillColorRGB(0.17, 0.24, 0.31)  # #2c3e50
    c.rect(50, page_height - 150, page_width - 100, 100, fill=True, stroke=False)
    
    # Main title
    c.setFillColorRGB(1, 1, 1)  # White text
    c.setFont("Helvetica-Bold", 28)
    c.drawCentredString(page_width / 2, page_height - 90, "App Store Assets Report")
    
    # App name
    c.setFont("Helvetica-Bold", 20)
    c.drawCentredString(page_width / 2, page_height - 120, app_name)
    
    # Reset to black
    c.setFillColorRGB(0, 0, 0)
    
    # App metadata section
    y_pos = page_height - 200
    
    if app_info:
        # Developer, version, rating box
        c.setFont("Helvetica-Bold", 14)
        c.drawString(50, y_pos, "App Information")
        y_pos -= 30
        
        # Create info table
        info_data = [
            ["App ID", app_id],
            ["Developer", app_info.get("developer", "N/A")],
            ["Version", app_info.get("version", "N/A")],
            ["Price", app_info.get("price", "N/A")],
            ["Rating", f"{app_info.get('rating', 0):.2f} ★ ({app_info.get('rating_count', 0):,} ratings)"],
            ["Genre", app_info.get("primary_genre", "N/A")],
        ]
        
        c.setFont("Helvetica", 11)
        for label, value in info_data:
            c.setFont("Helvetica-Bold", 11)
            c.drawString(50, y_pos, f"{label}:")
            c.setFont("Helvetica", 11)
            c.drawString(200, y_pos, str(value))
            y_pos -= 20
    else:
        # Minimal info
        c.setFont("Helvetica", 12)
        c.drawString(50, y_pos, f"App ID: {app_id}")
        y_pos -= 40
    
    # Download summary statistics
    y_pos -= 20
    c.setFont("Helvetica-Bold", 14)
    c.drawString(50, y_pos, "Download Summary")
    y_pos -= 30
    
    total_logos = sum(1 for r in results if r.get("logo_path"))
    total_screenshots = sum(r.get("screenshot_count", 0) for r in results)
    total_countries = len(results)
    
    summary_data = [
        ["Total Countries", str(total_countries)],
        ["Logos Downloaded", f"{total_logos}/{total_countries}"],
        ["Screenshots Downloaded", str(total_screenshots)],
        ["Download Date", datetime.now().strftime("%Y-%m-%d %H:%M:%S")],
    ]
    
    c.setFont("Helvetica", 11)
    for label, value in summary_data:
        c.setFont("Helvetica-Bold", 11)
        c.drawString(50, y_pos, f"{label}:")
        c.setFont("Helvetica", 11)
        c.drawString(250, y_pos, value)
        y_pos -= 20
    
    # Footer note
    c.setFont("Helvetica-Oblique", 9)
    c.setFillColorRGB(0.5, 0.5, 0.5)
    c.drawCentredString(page_width / 2, 50, "Generated by Screen ASO Asset Downloader")
    c.setFillColorRGB(0, 0, 0)


def _create_table_of_contents(
    c: canvas.Canvas,
    page_width: float,
    page_height: float,
    results: List[Dict[str, Any]]
) -> None:
    """Table of contents with country list and page numbers."""
    
    c.setFont("Helvetica-Bold", 24)
    c.drawString(50, page_height - 80, "Table of Contents")
    
    y_pos = page_height - 130
    
    # Section headers
    sections = [
        ("Cover Page", 1),
        ("Table of Contents", 2),
        ("Logo Comparison", 3),
        ("Screenshot Comparison", 4),
    ]
    
    c.setFont("Helvetica-Bold", 12)
    c.drawString(50, y_pos, "Section")
    c.drawString(page_width - 150, y_pos, "Page")
    y_pos -= 5
    
    # Draw line
    c.setLineWidth(1)
    c.line(50, y_pos, page_width - 50, y_pos)
    y_pos -= 20
    
    # List sections
    c.setFont("Helvetica", 11)
    for section_name, page_num in sections:
        c.drawString(60, y_pos, section_name)
        c.drawString(page_width - 150, y_pos, str(page_num))
        y_pos -= 18
    
    # Country details section
    y_pos -= 20
    c.setFont("Helvetica-Bold", 12)
    c.drawString(60, y_pos, "Country Details")
    y_pos -= 20
    
    # List all countries with their page numbers
    c.setFont("Helvetica", 10)
    page_num = 5  # Country pages start at 5
    for result in results:
        country = result["country"].upper()
        logo_status = "✓" if result.get("logo_path") else "✗"
        screenshot_count = result.get("screenshot_count", 0)
        
        text = f"  • {country} - Logo: {logo_status}, Screenshots: {screenshot_count}"
        c.drawString(70, y_pos, text)
        c.drawString(page_width - 150, y_pos, str(page_num))
        y_pos -= 16
        page_num += 1
        
        if y_pos < 100:
            break


def _create_logo_comparison_grid(
    c: canvas.Canvas,
    page_width: float,
    page_height: float,
    app_name: str,
    results: List[Dict[str, Any]]
) -> None:
    """Grid showing all country logos side by side."""
    
    c.setFont("Helvetica-Bold", 20)
    c.drawString(50, page_height - 60, "Logo Comparison - All Countries")
    
    # Grid configuration
    logos_per_row = 4
    logo_size = 120
    padding = 30
    start_x = 80
    start_y = page_height - 120
    
    x_pos = start_x
    y_pos = start_y
    col = 0
    
    for result in results:
        country = result["country"].upper()
        logo_path = result.get("logo_path")
        
        if logo_path and Path(logo_path).exists():
            try:
                # Draw logo
                c.drawImage(
                    logo_path,
                    x_pos,
                    y_pos - logo_size,
                    width=logo_size,
                    height=logo_size,
                    preserveAspectRatio=True
                )
                
                # Country label
                c.setFont("Helvetica-Bold", 11)
                c.drawCentredString(x_pos + logo_size / 2, y_pos - logo_size - 15, country)
                
            except Exception as e:
                # Draw placeholder box
                c.setStrokeColorRGB(0.8, 0.8, 0.8)
                c.setFillColorRGB(0.95, 0.95, 0.95)
                c.rect(x_pos, y_pos - logo_size, logo_size, logo_size, fill=True)
                c.setFillColorRGB(0, 0, 0)
                c.setFont("Helvetica", 9)
                c.drawCentredString(x_pos + logo_size / 2, y_pos - logo_size / 2, "Error")
                c.drawCentredString(x_pos + logo_size / 2, y_pos - logo_size - 15, country)
        else:
            # Draw empty placeholder
            c.setStrokeColorRGB(0.8, 0.8, 0.8)
            c.setFillColorRGB(0.95, 0.95, 0.95)
            c.rect(x_pos, y_pos - logo_size, logo_size, logo_size, fill=True, stroke=True)
            c.setFillColorRGB(0.5, 0.5, 0.5)
            c.setFont("Helvetica", 10)
            c.drawCentredString(x_pos + logo_size / 2, y_pos - logo_size / 2, "No Logo")
            c.setFillColorRGB(0, 0, 0)
            c.setFont("Helvetica-Bold", 11)
            c.drawCentredString(x_pos + logo_size / 2, y_pos - logo_size - 15, country)
        
        # Move to next position
        col += 1
        if col >= logos_per_row:
            col = 0
            x_pos = start_x
            y_pos -= (logo_size + padding + 20)
        else:
            x_pos += (logo_size + padding)
        
        # Check if we need a new page
        if y_pos < 100:
            c.showPage()
            c.setFont("Helvetica-Bold", 20)
            c.drawString(50, page_height - 60, "Logo Comparison (continued)")
            x_pos = start_x
            y_pos = page_height - 120
            col = 0


def _create_screenshot_comparison_grid(
    c: canvas.Canvas,
    page_width: float,
    page_height: float,
    app_name: str,
    results: List[Dict[str, Any]]
) -> None:
    """Grid showing first screenshot from each country."""
    
    c.setFont("Helvetica-Bold", 20)
    c.drawString(50, page_height - 60, "Screenshot Comparison - First Screenshots")
    
    # Grid configuration
    screenshots_per_row = 3
    screenshot_height = 200
    padding = 20
    start_x = 60
    start_y = page_height - 120
    
    x_pos = start_x
    y_pos = start_y
    col = 0
    
    for result in results:
        country = result["country"].upper()
        screenshot_paths = result.get("screenshot_paths", [])
        
        if screenshot_paths and Path(screenshot_paths[0]).exists():
            try:
                # Load image and calculate width
                img = Image.open(screenshot_paths[0])
                img_width, img_height = img.size
                scale = screenshot_height / img_height
                display_width = img_width * scale
                
                # Draw screenshot
                c.drawImage(
                    screenshot_paths[0],
                    x_pos,
                    y_pos - screenshot_height,
                    width=display_width,
                    height=screenshot_height,
                    preserveAspectRatio=True,
                    mask='auto'
                )
                
                # Country label + screenshot count
                c.setFont("Helvetica-Bold", 10)
                label = f"{country} (1/{len(screenshot_paths)})"
                c.drawCentredString(x_pos + display_width / 2, y_pos - screenshot_height - 15, label)
                
            except Exception as e:
                # Draw placeholder
                c.setStrokeColorRGB(0.8, 0.8, 0.8)
                c.setFillColorRGB(0.95, 0.95, 0.95)
                c.rect(x_pos, y_pos - screenshot_height, 80, screenshot_height, fill=True)
                c.setFillColorRGB(0, 0, 0)
                c.setFont("Helvetica", 9)
                c.drawCentredString(x_pos + 40, y_pos - screenshot_height / 2, "Error")
        else:
            # Draw empty placeholder
            c.setStrokeColorRGB(0.8, 0.8, 0.8)
            c.setFillColorRGB(0.95, 0.95, 0.95)
            c.rect(x_pos, y_pos - screenshot_height, 80, screenshot_height, fill=True, stroke=True)
            c.setFillColorRGB(0.5, 0.5, 0.5)
            c.setFont("Helvetica", 10)
            c.drawCentredString(x_pos + 40, y_pos - screenshot_height / 2, "No")
            c.drawCentredString(x_pos + 40, y_pos - screenshot_height / 2 - 15, "Screenshot")
            c.setFillColorRGB(0, 0, 0)
        
        # Country label for empty too
        if not screenshot_paths:
            c.setFont("Helvetica-Bold", 10)
            c.drawCentredString(x_pos + 40, y_pos - screenshot_height - 15, country)
        
        # Move to next position
        col += 1
        if col >= screenshots_per_row:
            col = 0
            x_pos = start_x
            y_pos -= (screenshot_height + padding + 25)
        else:
            x_pos += (250 + padding)
        
        # Check if we need a new page
        if y_pos < 100:
            c.showPage()
            c.setFont("Helvetica-Bold", 20)
            c.drawString(50, page_height - 60, "Screenshot Comparison (continued)")
            x_pos = start_x
            y_pos = page_height - 120
            col = 0


async def run_download(args: Namespace) -> None:
    """CLI üzerinden indirme işlemini çalıştır."""
    
    # Ülke listesini hazırla
    if args.countries:
        countries = [c.strip().lower() for c in args.countries.split(",")]
    else:
        countries = DEFAULT_COUNTRIES
    
    # Dil haritası oluştur (opsiyonel)
    language_map = {}
    if args.languages:
        lang_pairs = args.languages.split(",")
        for pair in lang_pairs:
            if ":" in pair:
                country, lang = pair.split(":", 1)
                language_map[country.strip().lower()] = lang.strip()
    
    # Output dizini
    output_dir = Path(args.output_dir) if args.output_dir else DEFAULT_OUTPUT_DIR
    
    # Downloader oluştur
    downloader = AppAssetDownloader(output_dir)
    
    # App name al (iTunes API'den)
    print(f"📱 App ID: {args.app_id}")
    metadata = await downloader.get_app_metadata(args.app_id, countries[0])
    
    if metadata:
        app_name = args.app_name or metadata.get("trackName", f"app_{args.app_id}")
    else:
        app_name = args.app_name or f"app_{args.app_id}"
    
    print(f"📱 App Name: {app_name}")
    print(f"🌍 Countries: {', '.join([c.upper() for c in countries])}")
    
    # Tüm ülkeler için indir
    results = await downloader.download_all_countries(
        args.app_id,
        app_name,
        countries,
        language_map
    )
    
    # JSON rapor kaydet
    json_output = output_dir / app_name / "download_report.json"
    json_output.parent.mkdir(parents=True, exist_ok=True)
    
    # Özet istatistikler
    total_screenshots = sum(r.get("screenshot_count", 0) for r in results)
    total_logos = sum(1 for r in results if r.get("logo_path"))
    
    # App bilgileri (metadata'dan)
    app_info = {}
    if metadata:
        app_info = {
            "developer": metadata.get("artistName"),
            "bundle_id": metadata.get("bundleId"),
            "version": metadata.get("version"),
            "price": metadata.get("formattedPrice", "Free"),
            "rating": metadata.get("averageUserRating"),
            "rating_count": metadata.get("userRatingCount"),
            "primary_genre": metadata.get("primaryGenreName"),
            "release_date": metadata.get("releaseDate"),
        }
    
    report_data = {
        "app_id": args.app_id,
        "app_name": app_name,
        "app_info": app_info,
        "downloaded_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "total_countries": len(results),
            "total_logos_downloaded": total_logos,
            "total_screenshots_downloaded": total_screenshots,
        },
        "countries": results,
    }
    
    with open(json_output, "w", encoding="utf-8") as f:
        json.dump(report_data, f, indent=2, ensure_ascii=False)
        f.write("\n")
    
    print(f"\n✓ JSON rapor kaydedildi: {json_output}")
    
    # PDF rapor oluştur (app_info'yu geç)
    if not args.no_pdf:
        pdf_output = output_dir / app_name / "assets_report.pdf"
        try:
            create_pdf_report(app_name, args.app_id, results, pdf_output, app_info)
        except Exception as e:
            print(f"✗ PDF oluşturma hatası: {e}")
    
    print(f"\n✅ Tamamlandı! Dosyalar: {output_dir / app_name}")


def parse_args() -> Namespace:
    """Komut satırı argümanları."""
    parser = ArgumentParser(
        description="App Store'dan logo ve screenshot indir (çoklu ülke desteği)"
    )
    parser.add_argument(
        "--app-id",
        required=True,
        help="App Store app ID (örn: 684119875)"
    )
    parser.add_argument(
        "--app-name",
        default=None,
        help="App adı (opsiyonel, belirtilmezse API'den alınır)"
    )
    parser.add_argument(
        "--countries",
        default=None,
        help=f"Virgülle ayrılmış ülke kodları (varsayılan: {','.join(DEFAULT_COUNTRIES)})"
    )
    parser.add_argument(
        "--languages",
        default=None,
        help="Ülke-dil eşleştirmesi (örn: 'tr:tr-tr,jp:ja-jp,us:en-us')"
    )
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help=f"Çıktı klasörü (varsayılan: {DEFAULT_OUTPUT_DIR})"
    )
    parser.add_argument(
        "--no-pdf",
        action="store_true",
        help="PDF rapor oluşturma"
    )
    
    return parser.parse_args()


async def main() -> None:
    """Ana fonksiyon."""
    args = parse_args()
    await run_download(args)


if __name__ == "__main__":
    asyncio.run(main())
