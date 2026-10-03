# OpenInspect-Trust M7: Yönetici Özeti (3 Ekim 2026, çalışma donduruldu)

**AI ile görsel karar verme yapıldı; bağımsız insan doğrulaması yapılmadı.**

## Ne sorduk?

Rastgele bölünmüş bir PCB kusur benchmark'ında, test görüntülerinin "akraba" örnekleri (makinenin tespit ettiği görsel benzerlik grupları) eğitimde yer alırsa skor ne kadar şişer? Kaynak (veri seti) değişince ne olur?

## Nasıl ölçtük?

- **Sabit test seti, iki koşul:** C0 test görüntülerinin grup arkadaşlarıyla eğitilir, C1 bunların yerine eşleştirilmiş başka örneklerle eğitilir. Test seti bayt bayt aynıdır.
- **Probe ve kontrol:** Test görüntülerinin bir kısmı "probe"dur (grup arkadaşı C0'da var), bir kısmı "kontrol"dür (hiçbir koşulda grup arkadaşı yok).
- **Tekrar:** 3 bağımsız tasarım (D0, D1, D2), toplam 8 eşleşmiş seed çifti. YOLO11n EVREN'de eğitildi, değerlendirme yerelde Ultralytics 8.3.0 ile yapıldı.

## Ana bulgular

| | sonuç |
|---|---|
| Probe etkisi, birleşik (3 tasarım) | **+3,7 mAP50-95 puan** (%95 aralık +1,7 / +5,7). 8 seed çiftinin 8'inde pozitif. |
| D0 birincil sonuç (önceden belirlenmiş) | +3,9 (seed+test belirsizliği dahil +0,4 / +7,6) |
| Kontroller | ortalama +0,2: sıfır civarı |
| Probe − kontrol, birleşik | +3,4 (+0,7 / +6,1). Plasebo p: D0 0,013 · D1 0,009 · D2 0,08 |
| Tüm test setinde etki | yaklaşık +2 puan: benchmark **ılımlı** düzeyde iyimser |
| En güçlü maruz kalan probe'lar (Δ>0,08) | **+6,9 puan**, 8/8 seed pozitif (yeni koşularda da doğrulandı). Zayıf maruz kalanlar yaklaşık 0. |
| Sürekli benzerlik ile kazanç ilişkisi | zayıf (Spearman 0,08–0,15) |
| D1 anomalisi | tekrarlanmadı: yeni seed'lerde kontroller −0,75 ve −1,68. Eğitim gürültüsü makul bir açıklama, ama kanıtlanmadı. |
| D2 | zayıfladı: 2. seed'de probe ve kontrol eşit arttı |
| Kaynak kayması | **−27 ile −47 puan** (PCB-Defect: 47,6 → 0,3). Grup maruziyetinin 10 katından büyük. |

## Doğru terim

**"Eğitim–test grup maruziyeti"** (makinece tespit edilmiş görsel benzerlik grupları). Bunu "near-duplicate leakage" diye adlandırmak yanlış olur: 60 probe–eş çiftinde hiç kopya bulunmadı, ilişkilerin çoğu aynı aile ya da yapısal benzerlik.

## Karar

**B: workshop / preprint için hazır.**

Gönderimden önce şiddetle önerilen tek adım: hazır 90 görüntü çiftinin iki kişi tarafından kör etiketlenmesi. Bu adım hesaplama gerektirmez.

Ek eğitim **gerekmiyor**. YOLO11s yalnızca tam konferans makalesi hedeflenirse anlamlı olur.

## EVREN/SSYZ için anlamı

Çalışma teknik geri bildirim için gönderilmeye değer. En değerli noktaları:
- kaynak kaymasının büyüklüğü,
- aynı konfigürasyonla yapılan tekrar koşularda 1–2 puanlık deterministik olmayan sonuçlar,
- koşu adı / veri seti eşleşme riskleri,
- tekrarlanabilir denetim hattı.
