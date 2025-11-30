# Gizlilik Politikası

_Son güncelleme: 2025-11-22_

## 1. Giriş

Screen ASO (bundan sonra “Araç”), Typer tabanlı bir CLI üstüne kurulu, ticari lisanslı ve özel kaynaklı bir App Store Optimizasyon yardımcısıdır. CLI ve yardımcı modüller açık kaynak olarak yayımlanmaz; yalnızca ücretli müşterilere veya yetkili iş ortaklarına dağıtılır. Araç tamamen sizin makinenizde çalışır ve siz açıkça bu şekilde yapılandırmadığınız sürece girdilerinizi, çıktılarını veya ortamınızı uzak sunuculara göndermez. Bu politika, `search`, `collect`, `analyze`, `assets download` veya `report generate` gibi komutları çalıştırırken aracın hangi verileri topladığını, işlediğini ve koruduğunu açıklar.

## 2. Topladığımız Veriler

- **İnceleme ve meta veriler:** Bir uygulama veya inceleme verilerini toplarken, Araç App Store ve Play Store’dan herkese açık meta verileri ve incelemeleri indirir. Bu yanıtlar inceleyenlerin isimleri, başlıkları veya kişisel tanımlayıcılar içerebilir; bunları paylaşmayız ve başka veri kaynaklarıyla zenginleştirmeyiz.
- **Kullanım bağlamı:** Kalıcı yapılandırma değerleri sadece komut satırı argümanları, ortam değişkenleri (ör. `APP_STORE_DEFAULT_COUNTRY`, `APP_STORE_HTTP_PROXY`) veya pipeline YAML dosyaları aracılığıyla verdiğiniz değerlerdir. Uygulama kimlikleri, arama anahtar kelimeleri, ülke/dil filtreleri ve limitler gibi girdiler yerel olarak oluşturulmuş çıktı dosyalarında saklanır.
- **Hesap yok:** Araç için kullanıcı hesapları, girişler veya takip çerezleri yoktur.

## 3. Verilerinizi Nasıl Kullanıyoruz

Varsayılan olarak tüm veriler yereldir. Araç toplanan inceleme ve meta verileri:

- pipeline’ları beslemek (`outputs/data/…`, `outputs/analyses/…`, `outputs/reports/…`);
- duygu, anahtar kelime ve meta veri analizlerini güçlendirmek;
- çevrimdışı inceleme için PDF veya Markdown raporları oluşturmak;
- uygulama mağazası varlıklarını `app_store_assets/` içine indirmek ve ham arama verilerini `app_store_search_results/` / `play_store_search_results/` klasörlerine yazmak.

Üretilen PDF’leri veya JSON’ları diğer hizmetlere yönlendirmek dışında hiçbir şey harici olarak gönderilmez.

## 4. Veri Temizliği ve Güvenlik

İnceleme metni kalıcı hale getirilmeden önce, Araç `core/privacy.py` ile başlık ve gövde alanlarındaki kişisel olarak tanımlanabilir bilgileri (PII) otomatik olarak gizler. İlk olarak Presidio analyzer/anonymizer bileşenini kullanmayı dener; eğer bu bağımlılıklara erişilemezse e-posta, telefon numarası ve kredi kartı gibi öğeleri regexp ile maskeleyen bir yedek strateji devreye girer. Veri toplama sonrası review `title`/`body` alanları `outputs/` altına yazıldığında veya PDF raporlarına eklendiğinde `[REDACTED]_TITLE` ve `[REDACTED]_BODY` gibi yer tutuculara dönüşür.

Geri kalan hassas verileri güvenli dizinlerde tutmanızı öneririz. Çıktı klasörleri append-only tasarlandığından silmekten kaçının ve gerekirse eski verileri arşivleyin.

## 5. Veri Saklama Süresi

Saklama süresi tamamen sizin kontrolünüzdedir. Araç yazdığı herhangi bir dosyayı silmez, bu nedenle dosya yaşam döngüsünü kendiniz yönetirsiniz. Pipeline çalıştırırken `outputs/`, `aso_results/`, `app_store_assets/` gibi klasörleri ihtiyaç dahilinde temizlemeyi veya arşivlemeyi değerlendirin.

## 6. Haklarınız ve Kontroller

Araç yerel olarak çalıştığından:

- Üretilen tüm dosyaları istediğiniz zaman görüntüleyebilir, taşıyabilir veya silebilirsiniz.
- Toplamayı durdurmak istiyorsanız CLI’yi durdurun ve komutu tekrarlamayın.
- Yerel verilerinizin nasıl kullanıldığına dair sorular için aşağıdaki e-posta adresiyle iletişime geçin.

## 7. Üçüncü Taraf Hizmetler

Araç, üçüncü taraf platformlardan (App Store ve Play Store) herkese açık verileri toplar. Bu servislerin kendi kullanım şartları vardır; aracın kullandığı verileri indirip analiz ederken bu platformların kurallarına uymak sizin sorumluluğunuzdadır.

**Sorumluluklarınız:**
- Topladığınız verileri toplama ve analiz etme hakkınız olduğundan emin olun
- Üçüncü taraf platformların oran sınırlamalarına ve robots.txt direktiflerine uyun
- Apple App Store İnceleme Yönergeleri ve Google Play Geliştirici Dağıtım Sözleşmesi'ne uyun
- Toplanan verileri platform politikalarını ihlal eden amaçlarla kullanmayın (ör. şartları ihlal eden rekabet istihbaratı)
- Üçüncü taraf hizmet şartlarının ihlalinden yalnızca siz sorumlusunuz; Screen ASO aracı sağlar ancak belirli kullanım durumlarını yetkilendirmez veya onaylamaz

## 8. Bu Politikanın Değişmesi

Araçta yapılan değişiklikleri yansıtmak için bu politikayı güncelleyebiliriz. Mümkün oldukça yeni sürümleri versiyonlayacağız ve bu belgeyi güncelleyerek en üstteki tarihi ifade edeceğiz.

## 9. İletişim

Bu gizlilik politikasıyla ilgili sorular için `support@screenaso.com` adresine e-posta gönderin.
