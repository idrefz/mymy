import pandas as pd
import streamlit as st
from sklearn.cluster import DBSCAN
import numpy as np

# ================ FUNGSI UTAMA ================
def organize_homepass(data, max_per_fat=16):
    """
    Mengelompokkan HomePass ke dalam FAT Area secara rapi.
    
    Args:
        data (list): Data HomePass dalam format [[HP1, HP2], [HP3, HP4], ...]
        max_per_fat (int): Maksimal HomePass per FAT Area (default: 16)
    
    Returns:
        DataFrame: Hasil pengelompokan dengan kolom [FAT_Area, HomePass_1, HomePass_2]
    """
    # 1. Flatten data dan buat DataFrame
    all_hp = [hp for pair in data for hp in pair]
    df = pd.DataFrame({'HomePass': all_hp})
    
    # 2. Ekstrak nomor HP untuk pengurutan
    df['HP_Num'] = df['HomePass'].str.extract('(\d+)').astype(int)
    
    # 3. Urutkan berdasarkan nomor HP
    df = df.sort_values('HP_Num').reset_index(drop=True)
    
    # 4. Buat pengelompokan FAT Area (misal: 16 HP per FAT)
    df['FAT_Area'] = [f'FAT A{(i//max_per_fat)+1:02d}' for i in range(len(df))]
    
    # 5. Format output dalam 2 kolom
    result = []
    for fat, group in df.groupby('FAT_Area'):
        group_hp = group['HomePass'].tolist()
        # Bagi menjadi 2 kolom
        half = (len(group_hp) + 1) // 2
        col1 = group_hp[:half]
        col2 = group_hp[half:]
        # Pad dengan empty string jika ganjil
        col2 += [''] * (len(col1) - len(col2))
        # Gabungkan ke hasil
        for hp1, hp2 in zip(col1, col2):
            result.append([fat, hp1, hp2])
    
    return pd.DataFrame(result, columns=['FAT_Area', 'HomePass_1', 'HomePass_2'])

# ================ TAMPILAN STREAMLIT ================
def main():
    st.set_page_config(page_title="FAT Area Organizer", layout="wide")
    st.title("📊 Organisasi HomePass ke FAT Area")

    # Input Data
    st.sidebar.header("⚙️ Pengaturan")
    max_per_fat = st.sidebar.number_input("Maksimal HP per FAT Area", 1, 50, 16)

    st.sidebar.header("📥 Input Data")
    sample_data = """Per/NK98,Per/NK80
Per/NK90,Per/NK77
Per/NK91,Per/NK84
Per/NK86,Per/NK87
Per/NK88,Per/NK89
Per/NK92,Per/NK90
Per/NK93,Per/NK91
Per/NK94,Per/NK95
Per/NK96,Per/NK97
Per/NK97,Per/NK99
Per/NK100,Per/NK80
Per/NK99,Per/NK79
Per/NK76,Per/NK43
Per/NK10,Per/NK40
Per/NK13,Per/NK16
Per/NK11,Per/NK14
Per/NK12,Per/NK18
Per/NK17,Per/NK19"""
    
    input_data = st.sidebar.text_area(
        "Masukkan data HomePass (format per baris: HP1,HP2):",
        value=sample_data,
        height=300
    )

    # Proses Data
    if st.button("🚀 Proses Pengelompokan"):
        try:
            # Parse input
            lines = [line.strip().split(',') for line in input_data.split('\n') if line.strip()]
            
            # Organisir data
            organized_data = organize_homepass(lines, max_per_fat)
            
            # Tampilkan hasil
            st.success("✅ Data berhasil diorganisir!")
            st.subheader("📋 Hasil Pengelompokan FAT Area")
            
            # Tampilkan per FAT Area dalam expander
            for fat_area, group in organized_data.groupby('FAT_Area'):
                with st.expander(f"{fat_area} ({len(group)} HomePass)", expanded=True):
                    col1, col2 = st.columns(2)
                    with col1:
                        st.write("\n".join(group['HomePass_1'].replace('', ' ').tolist()))
                    with col2:
                        st.write("\n".join(group['HomePass_2'].replace('', ' ').tolist()))
            
            # Ekspor ke CSV
            csv = organized_data.to_csv(index=False).encode('utf-8')
            st.download_button(
                label="📥 Download sebagai CSV",
                data=csv,
                file_name="fat_area_organization.csv",
                mime="text/csv"
            )
            
        except Exception as e:
            st.error(f"❌ Error: {str(e)}")

if __name__ == "__main__":
    main()
