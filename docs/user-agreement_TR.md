# Kullanıcı Sözleşmesi

_Son güncelleme: 2025-11-22_

## 1. Şartları Kabul

Screen ASO (`aso-cli`) kullandığınız sürece bu şartları ve ileride yapılabilecek güncellemeleri kabul etmiş sayılırsınız. Kabul etmiyorsanız CLI’yi çalıştırmayı veya ilgili varlıkları bir web sitesinde yayınlamayı durdurun.

## 2. Erişim ve Uygunluk

Screen ASO ticari bir lisansla dağıtılır ve “olduğu gibi” sağlanır. Lisans, geliştiriciden satın alma yoluyla veya yazılı onayla verilir; CLI, yardımcı modüller ve dokümantasyon kapalı kaynak olarak kalır. Python 3.10+, `requirements.txt`’te listelenen bağımlılıklar ve isteğe bağlı olarak `python -m crawl4ai install-browsers` ile kurulan tarayıcı altyapısına sahip olmanız gerekir. Lisans anahtarları, yükleyiciler ve depo içeriğini gizli tutun—izinsiz dağıtım, açık kaynakta yayımlama veya kodu barındırma, Araç’ı kullanma hakkınızı sona erdirir. Veri toplama veya varlık indirme sırasında bağlandığınız üçüncü taraf hesaplar (Apple Developer, Google Play Console vb.) sizin sorumluluğunuzdadır.

## 3. Kabul Edilebilir Kullanım

- Erişim izniniz olmayan içerikleri toplamak için Araç’ı kullanmayın.
- App Store, Play Store ve kullandığınız API’lerin uyguladığı oran sınırlamalarına saygı gösterin.
- Diğer satıcıların özel veri modellerini tersine mühendislik yapmayın veya verileri kötüye kullanmayın.

Bu kuralların ihlali oran sınırlaması, hukuki sonuçlar veya CLI’yi kullanma hakkınızın sonlandırılmasıyla sonuçlanabilir.

## 4. Çıktılar ve Veriler

Üretilen dosyalar `outputs/`, `app_store_assets/`, `aso_results/`, `app_store_search_results/` ve `play_store_search_results/` gibi dizinlerde tutulur. Bu klasörler append-only olup içerikleri kendiniz silmeli veya arşivlemelisiniz. İnceleme metinleri JSON veya PDF raporlarına yazılmadan önce (`core/privacy.py`’de anlatıldığı üzere) otomatik olarak temizlenir. Topladığınız verileri saklama, paylaşma veya silme sorumluluğu bulunduğunuz yargı bölgelerinin yasaları çerçevesindedir.

## 5. Gizlilik ve Güvenlik

Araç yerel dosyalarınızı başka bir yere göndermez. Komut satırı argümanlarına yapıştırdığınızlardan başka telemetri veya kişisel bilgi toplamayız. Ortam değişkenleri (ör. proxy ayarları) veya pipeline tanımları yapılandırıyorsanız gizli bilgileri paylaşılan versiyon kontrolüne eklemeyin. Maskeleme araçları e-posta, telefon numarası, isim ve kredi kartı bilgilerine karşı koruma sağlar, ancak saklamaya karar verdiğiniz hassas çıktılardan siz sorumlusunuz.

## 6. Fikri Mülkiyet

Bu depodaki tüm kod geliştiricinin mülkiyetinde kalır ve üzerinde anlaşılmış ticari şartlarla lisanslanmıştır. Uygulama meta verileri, inceleme alıntıları ve varlıklar Apple, Google ve uygulama yayıncılarının mülkiyetindedir. Araç’ı sadece herkese açık verileri analiz etmek için kullanabilirsiniz; üçüncü taraf içeriği sahiplenemez, kaynak platformların kurallarını veya ticari sözleşmenizi ihlal edecek şekilde yeniden yayımlayamazsınız.

## 7. Feragatnameler

ARAÇ HERHANGİ BİR GARANTİ VERMEDEN SUNULUR. TOPLANAN VERİLERİN DOĞRU, TAM VEYA ERİŞİLEBİLİR OLACAĞINA DAİR BİR GARANTİ YOKTUR (App Store/Play Store erişilebilirlikleri değişebilir). KULLANIM RİSK SİZE AİTTİR.

## 8. Sorumluluğun Sınırlandırılması

Screen ASO veya KATKIDA BULUNANLAR, CLI KULLANIMINIZLA İLGİLİ DOLAYLI, TESADÜFİ, SONUÇSAL VEYA CEZALANDIRICI ZARARLARDAN SORUMLU DEĞİLDİR, MİKTAR NE OLURSA OLSUN. TOPLAM SORUMLULUK, ARAÇ’I İNDİRME, YÜKLEME VEYA ÇALIŞTIRMAK İÇİN ÖDEDİĞİNİZ TUTARLA SINIRLANIR (VARSA).

## 9. Değişiklikler ve Sonlandırma

Aracı istediğiniz zaman güncelleyebilir veya sonlandırabiliriz. Güncelleme geri uyumluluğu etkiliyorsa bunu sürüm notlarında belirtiriz. CLI’yi kullanmayı bıraktığınız anda bu sözleşme kapsamındaki haklarınız sona erer.

## 10. Geçerli Hukuk ve İletişim

Bu şartlar Aracı çalıştırdığınız ülkenin yasalarına tabidir. Sorular veya kötüye kullanım bildirmek için `support@screenaso.com` adresine e-posta gönderin.
