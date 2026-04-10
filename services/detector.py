import pandas as pd
import numpy as np

class AnomalyDetector:
    def __init__(self, threshold=3.0):
        self.threshold = threshold  # درجة الحساسية (كلما زادت قلّت التنبيهات) [cite: 4]

    def detect_rolling_mad(self, df, window=7):
        """
        تكتشف الشذوذ بناءً على 'الوسيط المتحرك' وانحرافه المطلق.
        """
        # حساب الوسيط المتحرك (Rolling Median) 
        df['median'] = df['cost_amount'].rolling(window=window, center=True).median()
        
        # حساب الانحراف المطلق عن الوسيط (MAD)
        df['deviation'] = np.abs(df['cost_amount'] - df['median'])
        df['mad'] = df['deviation'].rolling(window=window, center=True).median()
        
        # تحديد نقاط الشذوذ (إذا تجاوز الانحراف العتبة المحددة) [cite: 2, 6]
        df['is_anomaly'] = df['deviation'] > (self.threshold * df['mad'])
        
        return df

# مثال سريع لاختبار المنطق
if __name__ == "__main__":
    # بيانات تجريبية: 10 أيام صرف طبيعي ويوم واحد شاذ [cite: 4]
    data = {
        'cost_amount': [100, 102, 98, 105, 101, 500, 99, 103, 97, 100]
    }
    df_test = pd.DataFrame(data)
    detector = AnomalyDetector()
    results = detector.detect_rolling_mad(df_test)
    print(results[results['is_anomaly'] == True]) # سيطبع اليوم الذي صرفت فيه 500