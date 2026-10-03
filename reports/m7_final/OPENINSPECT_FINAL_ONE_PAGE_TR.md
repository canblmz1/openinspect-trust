# OpenInspect-Trust: tek sayfalık özet (3 Ekim 2026)

**Problem.** Endüstriyel görüntü veri setleri rastgele bölündüğünde, aynı karttan ya da aynı tasarımdan gelen görüntüler hem eğitime hem teste düşebilir. Bu durumda benchmark skoru gerçekte olduğundan iyi görünebilir. Ayrıca modeller çoğu zaman yeni bir kaynakta (yeni hat, yeni kamera) test edilmez.

**Deney.**
- Üç açık PCB kusur veri seti birleştirildi: 4.420 görüntü, 4 sınıf.
- Akraba görüntüler makine ile gruplandı: görsel benzerlik, crop kaynağı ve kart kimliği.
- İki eğitim seti bayt bayt aynı tek bir test setinde karşılaştırıldı. Fark yalnızca belirlenmiş test görüntülerinin ("probe") grup arkadaşlarının eğitimde olup olmamasıydı. Grup arkadaşı hiçbir eğitimde olmayan "kontrol" görüntüleri negatif kontroldü.
- 3 bağımsız tasarım ve 8 seed çifti kullanıldı. YOLO11n EVREN'de eğitildi, değerlendirme yerelde tek bir değerlendiriciyle yapıldı.

**Ana sonuç.**
- Maruz kalan görüntülerde skor ortalama **+3,7 mAP50-95 puan** arttı (%95: +1,7 / +5,7), 8 seed çiftinin 8'inde pozitif.
- Kontrol görüntüleri neredeyse değişmedi (+0,2).
- Tüm test setinde etki yaklaşık +2 puan, yani benchmark **ılımlı** düzeyde iyimser.
- Kazanç en çok, eğitimdeki benzeri en yakın olan görüntülerde görüldü (+6,9).

**Neyi kanıtlamıyor?**
- **Kopya veri sızıntısı değil.** AI incelemesi 60 çiftte hiç kopya bulmadı; doğru terim "eğitim–test grup maruziyeti".
- **Her tasarımda tekrarlanmadı.** Bir tasarımın ikinci seed'inde etki görülmedi.
- **Benzerlik ile kazanç arasında düzgün bir ilişki yok.** Sürekli ilişki zayıf.
- **Sahadaki performans hakkında bilgi vermiyor.**

**Kaynak kayması.** Hiç görülmemiş bir kaynakta skor **27–47 puan** düştü (PCB-Defect: 47,6 → 0,3). Görüntü boyutu ve formatı kaynağı %100 ele veriyor; bu yüzden düşüş kusur sınıfını bilmemekten değil, edinim farkından kaynaklanıyor. Pratikte en önemli ders bu: yeni hat ya da kamera riski, grup maruziyetinden yaklaşık 10 kat büyük.

**Neden önemli?**
- PCB benchmark'larında modeller arası farklar çoğu zaman 1–3 puan. Bu farklar grup maruziyeti ve eğitim tekrarları arasındaki farklarla aynı büyüklükte.
- Grup-farkında bölme, çoklu seed ve kaynak-dışı test, güvenilir değerlendirme için gerekli.

**Sınırlar.**
- Bağımsız insan doğrulaması yok; yalnızca AI ile görsel inceleme yapıldı.
- Gruplar makine ile tespit edildi.
- Tek model (YOLO11n), tek alan; tasarım başına 2–3 seed.
- EVREN eğitimleri birebir tekrarlanabilir değil (1–2 puan fark).

**Yayın durumu.**
- Çalışma donduruldu; yeni eğitim planlanmıyor.
- Karar: **workshop / arXiv preprint için hazır.**
- Taslak ve LaTeX paketi hazır, ama PDF henüz derlenmedi (bu makinede LaTeX kurulu değil).
- Gönderim öncesi önerilen tek iş: 90 hazır görüntü çiftinin iki kişi tarafından kör etiketlenmesi.
