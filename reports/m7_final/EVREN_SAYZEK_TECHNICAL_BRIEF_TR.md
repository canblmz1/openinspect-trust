# OpenInspect-Trust: EVREN / SSYZ / SAYZEK için teknik not

*3 Ekim 2026 · Hedef okuyucu: platform ve ML mühendisleri · Bu bir satış dokümanı değildir.*

**AI ile görsel karar verme yapıldı; bağımsız insan doğrulaması yapılmadı.**

## 1. Ne test edildi?

Üç açık PCB kusur veri seti birleştirildi: DsPCBSD+, PCB-IND ve PCB-Defect (4.420 görüntü, 4 ortak sınıf). İki soru soruldu:

1. **Grup maruziyeti.** Bir test görüntüsünün "akraba" görüntüleri eğitimde varsa, o görüntüdeki skor ne kadar artar? Akrabalık makine ile tespit edildi: DINOv2 benzerlik grupları, crop kaynakları ve kaynak meta verisindeki kart kimliği.
2. **Kaynak kayması.** Hiç görülmemiş bir kaynakta skor ne kadar düşer?

Deney tasarımı:

- C0 ve C1 eğitim setleri, bayt bayt aynı tek bir test seti üzerinde karşılaştırıldı. Fark yalnızca şu: C0 "probe" test görüntülerinin grup arkadaşlarını içerir, C1 bunların yerine eşleştirilmiş başka görüntüleri içerir. Maruz kalmayan "kontrol" görüntüleri negatif kontrol işlevi görür.
- 3 bağımsız tasarım ve 8 eşleşmiş seed çifti kullanıldı. Toplam 31 YOLO11n işi EVREN'de koşuldu.
- Değerlendirme yerelde ve tek bir değerlendiriciyle yapıldı (Ultralytics 8.3.0). Dashboard metrikleri kullanılmadı.

## 2. Benchmark güvencesi neden önemli?

Rastgele bölünmüş endüstriyel veri setlerinde aynı karttan, aynı yerleşimden ya da aynı çekim oturumundan gelen görüntüler hem eğitime hem teste düşebilir. Bu durumda raporlanan doğruluğun bir kısmı "kusur tespiti" değil, "kartı tanıma" olur. Modeller arasında birkaç puanlık farklarla karar verilen ortamlarda bu sistematik bir hata kaynağıdır.

## 3. Sonuç: grup maruziyeti

Sayılar mAP50-95 puanı cinsindendir; ayrıntılı tablolar `FINAL_GROUP_EXPOSURE_RESULT.md` dosyasında.

| | sonuç |
|---|---|
| Maruz kalan (probe) görüntülerde kazanç, 3 tasarım birleşik | **+3,7** (%95: +1,7 / +5,7). 8/8 seed çiftinde pozitif. |
| Önceden belirlenmiş birincil sonuç (D0 probe) | +3,91 (seed + test belirsizliği dahil +0,41 / +7,65) |
| Kontroller | ortalama +0,2 |
| Probe − kontrol, birleşik | +3,4 (+0,7 / +6,1). Tasarım bazında tutarlılık karışık (aşağıda). |
| Tüm test seti | yaklaşık +2 puan, yani benchmark **ılımlı** düzeyde iyimser |
| En güçlü maruz kalan probe'lar | +6,9 (8/8 seed pozitif). Benzerlikle sürekli ilişki zayıf. |

Tekrarlanabilirlik sonuçları:

- **D1:** İlk seed'de kontroller de +3,1 arttı. Ek iki seed'de bu tekrar etmedi (−0,75 ve −1,68).
- **D2:** İkinci seed'de probe'a özgü kazanç görülmedi.

Terminoloji: AI görsel incelemesi 60 probe–eş çiftinde **hiç kopya bulmadı**; ilişkilerin çoğu aynı tasarım ailesi ya da yapısal benzerlik. Bu yüzden bulgu "near-duplicate leakage" değil, **"eğitim–test grup maruziyeti"** olarak adlandırılıyor.

## 4. Sonuç: kaynak kayması

| tutulan kaynak | aynı kaynak (dağılım içi) | kaynak hiç görülmeden |
|---|---|---|
| DsPCBSD+ | 43,7 | 16,4 |
| PCB-IND | 56,8 | 19,2 |
| PCB-Defect | 47,6 | 0,3 |

- **PCB-Defect'teki çöküş değerlendirme hatası değil.** O kaynağı gören bir model aynı görüntülerde 47,6 alıyor. Görmeyen model, laboratuvarda üretilmiş kartlardaki normal bakır yolları "spurious copper" olarak işaretliyor.
- **Görüntü boyutu ve dosya formatı tek başına kaynağı %100 tahmin ediyor.** Yani bu sonuç kusur sınıfını öğrenememe değil, **edinim/kaynak kayması** ölçüyor.
- **Pratik sonuç:** yeni bir hat, tarayıcı ya da kart ailesi, grup maruziyetinden yaklaşık 10 kat daha büyük bir risk.

## 5. EVREN kullanımından gözlemler

1. **Deterministik olmama.** Aynı veri seti versiyonu, seed ve konfigürasyonla koşulan işler farklı sonuç verdi. Checkpoint'lerde `deterministic=True` olmasına rağmen alt kümelerde fark 1–2 puana ulaştı: bir replikat çiftinde genelde 1,13, kontrol görüntülerinde 2,22 puan. Tek seed'li "birkaç puanlık" karşılaştırmalar bu nedenle güvenilir değil.
2. **Koşu adı / veri seti uyuşmazlığı riski.** M7'de birkaç iş, bir önceki işin koşu adı korunurken farklı bir veri seti ya da seed ile başlatıldı; bir işin koşu adı ise boş kaldı. Analizde işler koşu adına göre değil, **veri seti versiyonu + seed** ile eşleştirildi. Bu risk kullanıcı hatasından doğuyor, ama arayüzde kolayca oluşuyor.
3. **Uygulanan ayarlar kaydı.** `/training/jobs/{id}/run-manifest` uç noktası tüm işler için 404 döndürdü. Efektif konfigürasyon checkpoint içindeki `train_args`'tan okundu.
4. **Varsayılanlar.** İşler `cos_lr=True` ve `label_smoothing=0.1` ile koştu. Bunlar planlanmış değerler değildi; muhtemelen arayüz varsayılanlarıydı. Tüm işlerde aynı oldukları için karşılaştırmayı bozmadılar.

## 6. Bu vaka çalışmasının işaret ettiği olası platform yetenekleri

Bunlar EVREN tarafından talep edilmedi. Yalnızca bu vaka çalışmasından çıkan **olası platform yetenekleri** olarak öneriliyor:

- **Dataset Assurance:** Bir veri seti versiyonu dondurulurken kaynak, lisans kanıtı, sınıf eşleme ve etiket denetimi özetinin otomatik çıkarılması.
- **Split Preflight:** Eğitim başlamadan önce train/val/test bölümleri arasında grup bağımlılığı kontrolü (meta veri anahtarları, crop kaynakları, görsel benzerlik).
- **Group-overlap Warning:** Test görüntülerinin ne kadarının eğitimde grup arkadaşı olduğunu gösteren uyarı ve oran.
- **Source-separability Audit:** Kaynak kimliğinin basit meta veriden (boyut, format) tahmin edilip edilemediğini raporlayan kontrol.
- **Source-held-out Validation:** Bir kaynağı ya da hattı tamamen dışarıda tutan değerlendirme şablonu.
- **Replikat ve tekrar desteği:** Aynı konfigürasyonun birden çok seed ile kolayca koşulması ve çalıştırma kaydında uygulanan ayarların görünür olması.

## 7. Sınırlar

- Bağımsız insan doğrulaması yok; gruplar makine ile tespit edildi.
- Tek mimari (YOLO11n), tek alan (PCB) kullanıldı; tasarım başına 2–3 seed var.
- Üretim hattı verisi kullanılmadı; sonuçlar sahadaki performansı tahmin etmez.

Ayrıntılar `reports/m7_final/` ve `paper/` klasörlerinde. Kod, manifestler ve analiz betikleri açık; platform iş kimlikleri paylaşılmıyor.
