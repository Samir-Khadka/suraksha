"""
Suraksha (सुरक्षा) — Disaster Management & Early Warning prototype API.

Data honesty contract: every response carries a `data_label`:
  - "live"     : fetched just now from a real upstream API (USGS / Open-Meteo /
                 NEMRC). Timestamps show when.
  - "verified" : curated from authoritative published sources (ICIMOD/UNDP 2026
                 glacial-lake assessment, IOM/MoHA open-space designation).
                 Facts are real; coordinates may be marked approximate.
  - "model"    : computed by Suraksha's transparent heuristic risk engine (NOT an
                 official DHM/NDRRMA forecast — prototype only)
  - "sample"   : illustrative seed data (should be shrinking to zero)
"""
import asyncio
import json
import math
import os
import re
import time
from datetime import datetime, timezone
from urllib.parse import quote

import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ------------------------------------------------------------ districts ----
# All 77 districts of Nepal (headquarters coordinates, province grouping).
DISTRICTS = [
    {"id": "bhojpur", "name_en": "Bhojpur", "name_ne": "भोजपुर", "lat": 27.17, "lon": 87.05, "hill": True, "province_en": "Koshi", "province_ne": "कोशी"},
    {"id": "dhankuta", "name_en": "Dhankuta", "name_ne": "धनकुटा", "lat": 26.98, "lon": 87.34, "hill": True, "province_en": "Koshi", "province_ne": "कोशी"},
    {"id": "ilam", "name_en": "Ilam", "name_ne": "इलाम", "lat": 26.91, "lon": 87.93, "hill": True, "province_en": "Koshi", "province_ne": "कोशी"},
    {"id": "jhapa", "name_en": "Jhapa", "name_ne": "झापा", "lat": 26.53, "lon": 88.08, "hill": False, "province_en": "Koshi", "province_ne": "कोशी"},
    {"id": "khotang", "name_en": "Khotang", "name_ne": "खोटाङ", "lat": 27.21, "lon": 86.8, "hill": True, "province_en": "Koshi", "province_ne": "कोशी"},
    {"id": "morang", "name_en": "Morang", "name_ne": "मोरङ", "lat": 26.4525, "lon": 87.2718, "hill": False, "province_en": "Koshi", "province_ne": "कोशी"},
    {"id": "okhaldhunga", "name_en": "Okhaldhunga", "name_ne": "ओखलढुङ्गा", "lat": 27.31, "lon": 86.5, "hill": True, "province_en": "Koshi", "province_ne": "कोशी"},
    {"id": "panchthar", "name_en": "Panchthar", "name_ne": "पाँचथर", "lat": 27.15, "lon": 87.77, "hill": True, "province_en": "Koshi", "province_ne": "कोशी"},
    {"id": "sankhuwasabha", "name_en": "Sankhuwasabha", "name_ne": "सङ्खुवासभा", "lat": 27.37, "lon": 87.2, "hill": True, "province_en": "Koshi", "province_ne": "कोशी"},
    {"id": "solukhumbu", "name_en": "Solukhumbu", "name_ne": "सोलुखुम्बु", "lat": 27.5, "lon": 86.59, "hill": True, "province_en": "Koshi", "province_ne": "कोशी"},
    {"id": "sunsari", "name_en": "Sunsari", "name_ne": "सुनसरी", "lat": 26.6, "lon": 87.15, "hill": False, "province_en": "Koshi", "province_ne": "कोशी"},
    {"id": "taplejung", "name_en": "Taplejung", "name_ne": "ताप्लेजुङ", "lat": 27.35, "lon": 87.67, "hill": True, "province_en": "Koshi", "province_ne": "कोशी"},
    {"id": "terhathum", "name_en": "Terhathum", "name_ne": "तेह्रथुम", "lat": 27.13, "lon": 87.57, "hill": True, "province_en": "Koshi", "province_ne": "कोशी"},
    {"id": "udayapur", "name_en": "Udayapur", "name_ne": "उदयपुर", "lat": 26.78, "lon": 86.72, "hill": True, "province_en": "Koshi", "province_ne": "कोशी"},
    {"id": "bara", "name_en": "Bara", "name_ne": "बारा", "lat": 27.03, "lon": 85.03, "hill": False, "province_en": "Madhesh", "province_ne": "मधेश"},
    {"id": "dhanusha", "name_en": "Dhanusha", "name_ne": "धनुषा", "lat": 26.73, "lon": 85.93, "hill": False, "province_en": "Madhesh", "province_ne": "मधेश"},
    {"id": "mahottari", "name_en": "Mahottari", "name_ne": "महोत्तरी", "lat": 26.65, "lon": 85.8, "hill": False, "province_en": "Madhesh", "province_ne": "मधेश"},
    {"id": "parsa", "name_en": "Parsa", "name_ne": "पर्सा", "lat": 27.0, "lon": 84.87, "hill": False, "province_en": "Madhesh", "province_ne": "मधेश"},
    {"id": "rautahat", "name_en": "Rautahat", "name_ne": "रौतहट", "lat": 26.77, "lon": 85.28, "hill": False, "province_en": "Madhesh", "province_ne": "मधेश"},
    {"id": "saptari", "name_en": "Saptari", "name_ne": "सप्तरी", "lat": 26.54, "lon": 86.75, "hill": False, "province_en": "Madhesh", "province_ne": "मधेश"},
    {"id": "sarlahi", "name_en": "Sarlahi", "name_ne": "सर्लाही", "lat": 26.87, "lon": 85.56, "hill": False, "province_en": "Madhesh", "province_ne": "मधेश"},
    {"id": "siraha", "name_en": "Siraha", "name_ne": "सिराहा", "lat": 26.66, "lon": 86.2, "hill": False, "province_en": "Madhesh", "province_ne": "मधेश"},
    {"id": "bhaktapur", "name_en": "Bhaktapur", "name_ne": "भक्तपुर", "lat": 27.67, "lon": 85.43, "hill": True, "province_en": "Bagmati", "province_ne": "बागमती"},
    {"id": "chitwan", "name_en": "Chitwan", "name_ne": "चितवन", "lat": 27.68, "lon": 84.43, "hill": False, "province_en": "Bagmati", "province_ne": "बागमती"},
    {"id": "dhading", "name_en": "Dhading", "name_ne": "धादिङ", "lat": 27.9, "lon": 84.9, "hill": True, "province_en": "Bagmati", "province_ne": "बागमती"},
    {"id": "dolakha", "name_en": "Dolakha", "name_ne": "दोलखा", "lat": 27.67, "lon": 86.03, "hill": True, "province_en": "Bagmati", "province_ne": "बागमती"},
    {"id": "kathmandu", "name_en": "Kathmandu", "name_ne": "काठमाडौं", "lat": 27.7172, "lon": 85.324, "hill": True, "province_en": "Bagmati", "province_ne": "बागमती"},
    {"id": "kavrepalanchok", "name_en": "Kavrepalanchok", "name_ne": "काभ्रेपलाञ्चोक", "lat": 27.62, "lon": 85.55, "hill": True, "province_en": "Bagmati", "province_ne": "बागमती"},
    {"id": "lalitpur", "name_en": "Lalitpur", "name_ne": "ललितपुर", "lat": 27.66, "lon": 85.33, "hill": True, "province_en": "Bagmati", "province_ne": "बागमती"},
    {"id": "makwanpur", "name_en": "Makwanpur", "name_ne": "मकवानपुर", "lat": 27.42, "lon": 85.03, "hill": True, "province_en": "Bagmati", "province_ne": "बागमती"},
    {"id": "nuwakot", "name_en": "Nuwakot", "name_ne": "नुवाकोट", "lat": 27.89, "lon": 85.16, "hill": True, "province_en": "Bagmati", "province_ne": "बागमती"},
    {"id": "ramechhap", "name_en": "Ramechhap", "name_ne": "रामेछाप", "lat": 27.39, "lon": 86.06, "hill": True, "province_en": "Bagmati", "province_ne": "बागमती"},
    {"id": "rasuwa", "name_en": "Rasuwa", "name_ne": "रसुवा", "lat": 28.1, "lon": 85.29, "hill": True, "province_en": "Bagmati", "province_ne": "बागमती"},
    {"id": "sindhuli", "name_en": "Sindhuli", "name_ne": "सिन्धुली", "lat": 27.25, "lon": 85.97, "hill": True, "province_en": "Bagmati", "province_ne": "बागमती"},
    {"id": "sindhupalchok", "name_en": "Sindhupalchok", "name_ne": "सिन्धुपाल्चोक", "lat": 27.77, "lon": 85.71, "hill": True, "province_en": "Bagmati", "province_ne": "बागमती"},
    {"id": "baglung", "name_en": "Baglung", "name_ne": "बागलुङ", "lat": 28.27, "lon": 83.59, "hill": True, "province_en": "Gandaki", "province_ne": "गण्डकी"},
    {"id": "gorkha", "name_en": "Gorkha", "name_ne": "गोरखा", "lat": 28.0, "lon": 84.63, "hill": True, "province_en": "Gandaki", "province_ne": "गण्डकी"},
    {"id": "kaski", "name_en": "Kaski", "name_ne": "कास्की", "lat": 28.2096, "lon": 83.9856, "hill": True, "province_en": "Gandaki", "province_ne": "गण्डकी"},
    {"id": "lamjung", "name_en": "Lamjung", "name_ne": "लमजुङ", "lat": 28.23, "lon": 84.38, "hill": True, "province_en": "Gandaki", "province_ne": "गण्डकी"},
    {"id": "manang", "name_en": "Manang", "name_ne": "मनाङ", "lat": 28.65, "lon": 84.24, "hill": True, "province_en": "Gandaki", "province_ne": "गण्डकी"},
    {"id": "mustang", "name_en": "Mustang", "name_ne": "मुस्ताङ", "lat": 28.7806, "lon": 83.7222, "hill": True, "province_en": "Gandaki", "province_ne": "गण्डकी"},
    {"id": "myagdi", "name_en": "Myagdi", "name_ne": "म्याग्दी", "lat": 28.34, "lon": 83.56, "hill": True, "province_en": "Gandaki", "province_ne": "गण्डकी"},
    {"id": "nawalparasi-east", "name_en": "Nawalparasi East", "name_ne": "नवलपरासी पूर्व", "lat": 27.65, "lon": 84.13, "hill": False, "province_en": "Gandaki", "province_ne": "गण्डकी"},
    {"id": "parbat", "name_en": "Parbat", "name_ne": "पर्वत", "lat": 28.22, "lon": 83.68, "hill": True, "province_en": "Gandaki", "province_ne": "गण्डकी"},
    {"id": "syangja", "name_en": "Syangja", "name_ne": "स्याङ्जा", "lat": 28.1, "lon": 83.87, "hill": True, "province_en": "Gandaki", "province_ne": "गण्डकी"},
    {"id": "tanahun", "name_en": "Tanahun", "name_ne": "तनहुँ", "lat": 27.98, "lon": 84.27, "hill": True, "province_en": "Gandaki", "province_ne": "गण्डकी"},
    {"id": "arghakhanchi", "name_en": "Arghakhanchi", "name_ne": "अर्घाखाँची", "lat": 27.97, "lon": 83.13, "hill": True, "province_en": "Lumbini", "province_ne": "लुम्बिनी"},
    {"id": "banke", "name_en": "Banke", "name_ne": "बाँके", "lat": 28.05, "lon": 81.62, "hill": False, "province_en": "Lumbini", "province_ne": "लुम्बिनी"},
    {"id": "bardiya", "name_en": "Bardiya", "name_ne": "बर्दिया", "lat": 28.23, "lon": 81.34, "hill": False, "province_en": "Lumbini", "province_ne": "लुम्बिनी"},
    {"id": "dang", "name_en": "Dang", "name_ne": "दाङ", "lat": 28.04, "lon": 82.49, "hill": False, "province_en": "Lumbini", "province_ne": "लुम्बिनी"},
    {"id": "rukum-east", "name_en": "Rukum East", "name_ne": "पूर्वी रुकुम", "lat": 28.62, "lon": 82.63, "hill": True, "province_en": "Lumbini", "province_ne": "लुम्बिनी"},
    {"id": "gulmi", "name_en": "Gulmi", "name_ne": "गुल्मी", "lat": 28.07, "lon": 83.25, "hill": True, "province_en": "Lumbini", "province_ne": "लुम्बिनी"},
    {"id": "kapilvastu", "name_en": "Kapilvastu", "name_ne": "कपिलवस्तु", "lat": 27.55, "lon": 83.05, "hill": False, "province_en": "Lumbini", "province_ne": "लुम्बिनी"},
    {"id": "nawalparasi-west", "name_en": "Nawalparasi West", "name_ne": "नवलपरासी पश्चिम", "lat": 27.52, "lon": 83.68, "hill": False, "province_en": "Lumbini", "province_ne": "लुम्बिनी"},
    {"id": "palpa", "name_en": "Palpa", "name_ne": "पाल्पा", "lat": 27.87, "lon": 83.55, "hill": True, "province_en": "Lumbini", "province_ne": "लुम्बिनी"},
    {"id": "pyuthan", "name_en": "Pyuthan", "name_ne": "प्यूठान", "lat": 28.1, "lon": 82.85, "hill": True, "province_en": "Lumbini", "province_ne": "लुम्बिनी"},
    {"id": "rolpa", "name_en": "Rolpa", "name_ne": "रोल्पा", "lat": 28.3, "lon": 82.77, "hill": True, "province_en": "Lumbini", "province_ne": "लुम्बिनी"},
    {"id": "rupandehi", "name_en": "Rupandehi", "name_ne": "रुपन्देही", "lat": 27.5, "lon": 83.45, "hill": False, "province_en": "Lumbini", "province_ne": "लुम्बिनी"},
    {"id": "dailekh", "name_en": "Dailekh", "name_ne": "दैलेख", "lat": 28.84, "lon": 81.71, "hill": True, "province_en": "Karnali", "province_ne": "कर्णाली"},
    {"id": "dolpa", "name_en": "Dolpa", "name_ne": "डोल्पा", "lat": 28.95, "lon": 82.88, "hill": True, "province_en": "Karnali", "province_ne": "कर्णाली"},
    {"id": "humla", "name_en": "Humla", "name_ne": "हुम्ला", "lat": 29.97, "lon": 81.83, "hill": True, "province_en": "Karnali", "province_ne": "कर्णाली"},
    {"id": "jajarkot", "name_en": "Jajarkot", "name_ne": "जाजरकोट", "lat": 28.7, "lon": 82.2, "hill": True, "province_en": "Karnali", "province_ne": "कर्णाली"},
    {"id": "jumla", "name_en": "Jumla", "name_ne": "जुम्ला", "lat": 29.28, "lon": 82.18, "hill": True, "province_en": "Karnali", "province_ne": "कर्णाली"},
    {"id": "kalikot", "name_en": "Kalikot", "name_ne": "कालीकोट", "lat": 29.15, "lon": 81.62, "hill": True, "province_en": "Karnali", "province_ne": "कर्णाली"},
    {"id": "mugu", "name_en": "Mugu", "name_ne": "मुगु", "lat": 29.55, "lon": 82.08, "hill": True, "province_en": "Karnali", "province_ne": "कर्णाली"},
    {"id": "salyan", "name_en": "Salyan", "name_ne": "सल्यान", "lat": 28.38, "lon": 82.16, "hill": True, "province_en": "Karnali", "province_ne": "कर्णाली"},
    {"id": "surkhet", "name_en": "Surkhet", "name_ne": "सुर्खेत", "lat": 28.6, "lon": 81.62, "hill": True, "province_en": "Karnali", "province_ne": "कर्णाली"},
    {"id": "rukum-west", "name_en": "Rukum West", "name_ne": "पश्चिम रुकुम", "lat": 28.63, "lon": 82.47, "hill": True, "province_en": "Karnali", "province_ne": "कर्णाली"},
    {"id": "achham", "name_en": "Achham", "name_ne": "अछाम", "lat": 29.13, "lon": 81.29, "hill": True, "province_en": "Sudurpashchim", "province_ne": "सुदूरपश्चिम"},
    {"id": "baitadi", "name_en": "Baitadi", "name_ne": "बैतडी", "lat": 29.55, "lon": 80.43, "hill": True, "province_en": "Sudurpashchim", "province_ne": "सुदूरपश्चिम"},
    {"id": "bajhang", "name_en": "Bajhang", "name_ne": "बझाङ", "lat": 29.55, "lon": 81.2, "hill": True, "province_en": "Sudurpashchim", "province_ne": "सुदूरपश्चिम"},
    {"id": "bajura", "name_en": "Bajura", "name_ne": "बाजुरा", "lat": 29.43, "lon": 81.35, "hill": True, "province_en": "Sudurpashchim", "province_ne": "सुदूरपश्चिम"},
    {"id": "dadeldhura", "name_en": "Dadeldhura", "name_ne": "डडेल्धुरा", "lat": 29.3, "lon": 80.59, "hill": True, "province_en": "Sudurpashchim", "province_ne": "सुदूरपश्चिम"},
    {"id": "darchula", "name_en": "Darchula", "name_ne": "दार्चुला", "lat": 29.85, "lon": 80.55, "hill": True, "province_en": "Sudurpashchim", "province_ne": "सुदूरपश्चिम"},
    {"id": "doti", "name_en": "Doti", "name_ne": "डोटी", "lat": 29.27, "lon": 80.94, "hill": True, "province_en": "Sudurpashchim", "province_ne": "सुदूरपश्चिम"},
    {"id": "kailali", "name_en": "Kailali", "name_ne": "कैलाली", "lat": 28.7076, "lon": 80.5814, "hill": False, "province_en": "Sudurpashchim", "province_ne": "सुदूरपश्चिम"},
    {"id": "kanchanpur", "name_en": "Kanchanpur", "name_ne": "कञ्चनपुर", "lat": 28.92, "lon": 80.34, "hill": False, "province_en": "Sudurpashchim", "province_ne": "सुदूरपश्चिम"},
]

# ------------------------------------------- real-data registries (verified) --
# GLOF registry: curated from the ICIMOD + UNDP + Government of Nepal assessment
# "Inventory of glacial lakes and identification of potentially dangerous glacial
# lakes in the Koshi, Gandaki and Karnali river basins" (2026 update):
# 47 Potentially Dangerous Glacial Lakes — 21 in Nepal, 25 in Tibet, 1 in India.
# The six below are Nepal's priority lakes: 4 in the $49.9M GLOF Sanjeevani
# Project (2026–2033, DHM + UNDP) + the 2 previously lowered.
GLOF_SUMMARY = {
    "pdgl_total": 47, "in_nepal": 21, "in_tibet": 25, "in_india": 1,
    "by_basin": {"Koshi": 42, "Gandaki": 3, "Karnali": 2},
    "mapped_lakes_nepal": 2070,
    "glofs_since_1977": 26,
    "source": "ICIMOD + UNDP + Government of Nepal (2026)",
    "data_label": "verified",
}
GLOF_LAKES = [
    {"id": "imja", "name_en": "Imja Tsho", "name_ne": "इम्जा छो",
     "lat": 27.8986, "lon": 86.9108, "coords": "verified",
     "district_en": "Solukhumbu", "district_ne": "सोलुखुम्बु", "basin_en": "Koshi",
     "level": "watch", "status_en": "Monitored — risk reduced",
     "status_ne": "निगरानी — जोखिम घटाइएको",
     "fact_en": "Lowered 3.4 m in 2016 (~4M m³ drained); early-warning sirens installed downstream.",
     "fact_ne": "सन् २०१६ मा ३.४ मि घटाइयो; तल्लो तटीय क्षेत्रमा पूर्वसूचना साइरन जडान।",
     "downstream_en": "Dingboche, Chhukhung", "data_label": "verified"},
    {"id": "tsho-rolpa", "name_en": "Tsho Rolpa", "name_ne": "छो रोल्पा",
     "lat": 27.8667, "lon": 86.4667, "coords": "verified",
     "district_en": "Dolakha", "district_ne": "दोलखा", "basin_en": "Koshi (Tama Koshi)",
     "level": "warning", "status_en": "High watch — re-expanding",
     "status_ne": "उच्च निगरानी — पुनः बढ्दै",
     "fact_en": "Partially drained ~3 m in 2000 (Nepal's first lake lowering); now expanding again to ~1.6 km².",
     "fact_ne": "सन् २००० मा आंशिक निकास; अहिले ~१.६ किमी² सम्म पुनः विस्तार।",
     "downstream_en": "Bedding, Na; Tama Koshi valley", "data_label": "verified"},
    {"id": "thulagi", "name_en": "Thulagi (Dona)", "name_ne": "ठुलागी (डोना)",
     "lat": 28.4939, "lon": 84.4744, "coords": "verified",
     "district_en": "Manang", "district_ne": "मनाङ", "basin_en": "Gandaki (Marsyangdi)",
     "level": "warning", "status_en": "Priority — GLOF Sanjeevani Project",
     "status_ne": "प्राथमिकता — ग्लोफ सञ्जीवनी आयोजना",
     "fact_en": "Rapidly expanding, unmitigated; slated for lowering under the $49.9M Sanjeevani Project (2026–2033).",
     "fact_ne": "तिव्र विस्तार, अव्यवस्थित; सन् २०२६–२०३३ सञ्जीवनी आयोजनामा निकास योजना।",
     "downstream_en": "Dharapani, Tal; Marsyangdi valley", "data_label": "verified"},
    {"id": "lower-barun", "name_en": "Lower Barun (Talopokhari)", "name_ne": "तल्लो बरुण",
     "lat": 27.7667, "lon": 87.1000, "coords": "verified",
     "district_en": "Sankhuwasabha", "district_ne": "सङ्खुवासभा", "basin_en": "Koshi (Barun/Arun)",
     "level": "warning", "status_en": "Priority — GLOF Sanjeevani Project",
     "status_ne": "प्राथमिकता — ग्लोफ सञ्जीवनी आयोजना",
     "fact_en": "Rapidly expanding moraine-dammed lake; Sanjeevani priority for lowering + monitoring.",
     "fact_ne": "तिव्र विस्तारित हिमताल; सञ्जीवनी आयोजनाको प्राथमिकता।",
     "downstream_en": "Barun valley settlements", "data_label": "verified"},
    {"id": "lumding", "name_en": "Lumding Tsho", "name_ne": "लुम्दिङ छो",
     "lat": 27.7500, "lon": 86.6200, "coords": "approximate",
     "district_en": "Solukhumbu", "district_ne": "सोलुखुम्बु", "basin_en": "Koshi",
     "level": "warning", "status_en": "Priority — GLOF Sanjeevani Project",
     "status_ne": "प्राथमिकता — ग्लोफ सञ्जीवनी आयोजना",
     "fact_en": "Sanjeevani priority; controlled drainage programmes have begun (DHM).",
     "fact_ne": "सञ्जीवनी प्राथमिकता; नियन्त्रित निकास कार्यक्रम सुरु।",
     "downstream_en": "Dudhkoshi tributary settlements", "data_label": "verified"},
    {"id": "hongu-2", "name_en": "Hongu 2", "name_ne": "होङ्गु २",
     "lat": 27.8000, "lon": 86.9300, "coords": "approximate",
     "district_en": "Solukhumbu", "district_ne": "सोलुखुम्बु", "basin_en": "Koshi",
     "level": "warning", "status_en": "Priority — GLOF Sanjeevani Project",
     "status_ne": "प्राथमिकता — ग्लोफ सञ्जीवनी आयोजना",
     "fact_en": "Sanjeevani priority; lowering + expanded early-warning planned (2026–2033).",
     "fact_ne": "सञ्जीवनी प्राथमिकता; निकास + पूर्वसूचना विस्तार योजना।",
     "downstream_en": "Hongu valley; Dudhkoshi", "data_label": "verified"},
]

# Shelter registry: the 83 open spaces identified by IOM + Ministry of Home
# Affairs (Feb 2013), designated in the Nepal Gazette; 33 were used by ~30,900
# displaced people in the 2015 Gorkha earthquake. Coordinates approximate.
SHELTERS = [
    {"id": "tundikhel", "name_en": "Tundikhel", "name_ne": "टुँडिखेल",
     "lat": 27.7000, "lon": 85.3150, "district_en": "Kathmandu", "district_ne": "काठमाडौं",
     "fact_en": "83-space IOM/MoHA designation (2013, gazetted); main 2015 displacement camp for months.",
     "data_label": "verified"},
    {"id": "ratna-park", "name_en": "Ratna Park", "name_ne": "रत्नपार्क",
     "lat": 27.7042, "lon": 85.3125, "district_en": "Kathmandu", "district_ne": "काठमाडौं",
     "fact_en": "83-space IOM/MoHA designation (2013, gazetted).",
     "data_label": "verified"},
    {"id": "dasharath", "name_en": "Dasharath Stadium", "name_ne": "दशरथ रङ्गशाला",
     "lat": 27.6939, "lon": 85.3161, "district_en": "Kathmandu", "district_ne": "काठमाडौं",
     "fact_en": "83-space IOM/MoHA designation (2013, gazetted); 2015 camp site.",
     "data_label": "verified"},
    {"id": "shankha-park", "name_en": "Shankha Park", "name_ne": "शङ्खपार्क",
     "lat": 27.7150, "lon": 85.3400, "district_en": "Kathmandu", "district_ne": "काठमाडौं",
     "fact_en": "83-space designation; government-managed camp in 2015.",
     "data_label": "verified"},
    {"id": "sano-gaucharan", "name_en": "Sano Gaucharan", "name_ne": "सानो गौचरन",
     "lat": 27.7089, "lon": 85.3226, "district_en": "Kathmandu", "district_ne": "काठमाडौं",
     "fact_en": "83-space designation; 2015 camp site.",
     "data_label": "verified"},
    {"id": "bhaktapur-durbar", "name_en": "Bhaktapur Durbar Square open area", "name_ne": "भक्तपुर दरबार क्षेत्र",
     "lat": 27.6722, "lon": 85.4278, "district_en": "Bhaktapur", "district_ne": "भक्तपुर",
     "fact_en": "83-space designation; government-managed camp in 2015.",
     "data_label": "verified"},
    {"id": "pulchowk-campus", "name_en": "Pulchowk Engineering Campus grounds", "name_ne": "पुल्चोक इन्जिनियरिङ क्याम्पस",
     "lat": 27.6817, "lon": 85.3250, "district_en": "Lalitpur", "district_ne": "ललितपुर",
     "fact_en": "83-space IOM/MoHA designation (2013, gazetted).",
     "data_label": "verified"},
    {"id": "tu-kirtipur", "name_en": "Tribhuvan University, Kirtipur", "name_ne": "त्रिभुवन विश्वविद्यालय, कीर्तिपुर",
     "lat": 27.6828, "lon": 85.2903, "district_en": "Kathmandu", "district_ne": "काठमाडौं",
     "fact_en": "83-space IOM/MoHA designation (2013, gazetted).",
     "data_label": "verified"},
    {"id": "un-park", "name_en": "UN Park", "name_ne": "यूएन पार्क",
     "lat": 27.6710, "lon": 85.3310, "district_en": "Lalitpur", "district_ne": "ललितपुर",
     "fact_en": "83-space IOM/MoHA designation (2013, gazetted).",
     "data_label": "verified"},
    {"id": "balaju-park", "name_en": "Balaju Park", "name_ne": "बालाजु पार्क",
     "lat": 27.7350, "lon": 85.2950, "district_en": "Kathmandu", "district_ne": "काठमाडौं",
     "fact_en": "83-space IOM/MoHA designation (2013, gazetted).",
     "data_label": "verified"},
]

ACTIONS = {
    "flood": {
        "en": ["Move to higher ground away from rivers",
               "Do not walk or drive through flooded roads",
               "Keep phone charged and documents dry"],
        "ne": ["नदीबाट टाढा अग्लो स्थानमा जानुहोस्",
               "डुबेका बाटोमा नहिँड्नुहोस्, गाडी नचलाउनुहोस्",
               "फोन चार्ज र कागजात सुख्खा राख्नुहोस्"]},
    "landslide": {
        "en": ["Leave slopes and cracked houses immediately",
               "Avoid travel on hill highways in heavy rain",
               "Listen for unusual rumbling sounds"],
        "ne": ["भिर र चर्केका घर तुरुन्त छोड्नुहोस्",
               "भारी वर्षामा पहाडी राजमार्ग यात्रा नगर्नुहोस्",
               "असामान्य गडगडाहट सुनेमा सतर्क रहनुहोस्"]},
    "earthquake": {
        "en": ["Drop, cover and hold on during shaking",
               "Move to open space after shaking stops",
               "Check gas and electricity; expect aftershocks"],
        "ne": ["कम्पन हुँदा निहुरनुहोस्, छोप्नुहोस्, समात्नुहोस्",
               "कम्पन रोकिएपछि खुला ठाउँमा जानुहोस्",
               "ग्यास र बिजुली जाँच्नुहोस्; परकम्प आउन सक्छ"]},
    "glof": {
        "en": ["Move to high ground immediately — do not wait",
               "Follow the marked evacuation route uphill",
               "Warn neighbours as you move"],
        "ne": ["तुरुन्त अग्लो ठाउँमा जानुहोस् — नपर्खनुहोस्",
               "तोकिएको बाटो हुँदै उकालो जानुहोस्",
               "जाँदाजाँदै छिमेकीलाई खबर गर्नुहोस्"]},
}

LEVELS = ["low", "moderate", "high", "critical"]  # index = severity
LEVEL_NE = {"low": "सामान्य", "moderate": "मध्यम", "high": "उच्च", "critical": "अति उच्च"}

# ------------------------------------------------------------------ http ---
# Sandbox note: the VM's NO_PROXY list contains bracketed IPv6 entries that
# httpx's trust_env parsing chokes on, so we bypass env parsing and pass the
# egress proxy explicitly. On normal hosts (no proxy vars) this is a direct
# connection.
def _make_client(timeout):
    proxy = (os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
             or os.environ.get("HTTP_PROXY") or os.environ.get("http_proxy"))
    kw = {"timeout": timeout, "trust_env": False,
          "headers": {"User-Agent": "Suraksha/0.1 (Nepal disaster early-warning prototype)"}}
    if proxy:
        kw["proxy"] = proxy
    # Egress proxy does TLS interception; its CA is in SSL_CERT_FILE on this VM.
    ca = os.environ.get("SSL_CERT_FILE")
    if ca and os.path.isfile(ca):
        kw["verify"] = ca
    return httpx.AsyncClient(**kw)

# ------------------------------------------------------------------ cache ---
_cache: dict = {}
_stale: dict = {}          # last-good data, served if upstream is down/rate-limited
_locks = {}                # single-flight locks per resource (prevents stampedes)

def _lock(key):
    lock = _locks.get(key)
    if lock is None:
        import asyncio as _aio
        lock = _aio.Lock()
        _locks[key] = lock
    return lock

def cache_get(key):
    entry = _cache.get(key)
    if entry and time.time() < entry["expires"]:
        return entry["data"]
    return None

def cache_set(key, data, ttl):
    _cache[key] = {"data": data, "expires": time.time() + ttl}

# ---------------------------------------------------------------- helpers ---
def haversine_km(lat1, lon1, lat2, lon2):
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))

def in_nepal(lat, lon):
    return 26.0 <= lat <= 31.0 and 80.0 <= lon <= 89.0

async def _get_with_retry(client, url, tries=3):
    """GET with backoff on 429/5xx — shared egress IPs get rate-limited."""
    last = None
    for i in range(tries):
        try:
            resp = await client.get(url)
            if resp.status_code == 429 and i < tries - 1:
                await asyncio.sleep(2 * (i + 1))
                continue
            resp.raise_for_status()
            return resp
        except httpx.HTTPStatusError as e:
            last = e
            code = e.response.status_code if e.response is not None else 0
            if code == 429 and i < tries - 1:
                await asyncio.sleep(2 * (i + 1))
                continue
            raise
    raise last

async def fetch_usgs():
    """Live earthquake feed from USGS (free, no key). Cached 10 min."""
    async with _lock("usgs"):
        hit = cache_get("usgs")
        if hit is not None:
            return hit, True
        url = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/4.5_month.geojson"
        try:
            async with _make_client(25) as client:
                resp = await _get_with_retry(client, url)
                raw = resp.json()
        except Exception:
            if "usgs" in _stale:                      # graceful degradation
                return _stale["usgs"], True
            raise
    quakes = []
    for f in raw.get("features", []):
        p, g = f["properties"], f["geometry"]
        lon, lat, depth = g["coordinates"]
        quakes.append({
            "id": f["id"], "mag": p.get("mag"), "place": p.get("place"),
            "time": datetime.fromtimestamp(p["time"] / 1000, tz=timezone.utc).isoformat(),
            "lat": lat, "lon": lon, "depth_km": depth,
            "tsunami": bool(p.get("tsunami")), "url": p.get("url"),
            "in_nepal": in_nepal(lat, lon),
            "dist_to_kathmandu_km": round(haversine_km(lat, lon, 27.7172, 85.3240), 1),
        })
    quakes.sort(key=lambda q: q["time"], reverse=True)
    cache_set("usgs", quakes, 600)
    _stale["usgs"] = quakes
    return quakes, False

MET_UA = {"User-Agent": "Suraksha/0.2 (https://github.com/Samir-Khadka/suraksha)"}
MET_WMO = {"clearsky": 0, "fair": 1, "partlycloudy": 2, "cloudy": 3, "fog": 45,
           "lightrainshowers": 61, "lightrain": 61, "lightsleetshowers": 61, "lightsleet": 61,
           "rainshowers": 63, "rain": 63, "sleetshowers": 63, "sleet": 63,
           "heavyrainshowers": 65, "heavyrain": 65, "heavysleetshowers": 65, "heavysleet": 65,
           "lightsnowshowers": 71, "lightsnow": 71, "snowshowers": 73, "snow": 73,
           "heavysnowshowers": 75, "heavysnow": 75}

def _met_wmo(symbol_code):
    base = (symbol_code or "").split("_")[0]
    if "thunder" in base:
        return 95
    return MET_WMO.get(base, 3)

def _npt_date(iso_ts):
    """Local Kathmandu date for an ISO timestamp."""
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo("Asia/Kathmandu")
    except Exception:  # noqa: BLE001
        from datetime import timedelta
        tz = timezone(timedelta(hours=5, minutes=45))
    dt = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(tz).date().isoformat()

async def _fetch_met_city(client, city):
    """One city from MET Norway Locationforecast 2.0 (free, no key)."""
    url = (f"https://api.met.no/weatherapi/locationforecast/2.0/compact"
           f"?lat={city['lat']}&lon={city['lon']}")
    resp = await client.get(url, headers=MET_UA)
    resp.raise_for_status()
    ts = resp.json()["properties"]["timeseries"]
    if not ts:
        raise ValueError("empty timeseries")
    first = ts[0]
    inst = first["data"]["instant"]["details"]
    n1 = (first["data"].get("next_1_hours") or {}).get("details", {})
    cur = {"temperature_2m": inst.get("air_temperature"),
           "precipitation": n1.get("precipitation_amount", 0),
           "wind_speed_10m": inst.get("wind_speed"),
           "weather_code": _met_wmo((first["data"].get("next_1_hours") or {})
                                    .get("summary", {}).get("symbol_code", ""))}
    days, order = {}, []
    for e in ts:
        d = _npt_date(e["time"])
        if d not in days:
            days[d] = {"tmin": 1e9, "tmax": -1e9, "precip": 0.0, "wet": 0, "n": 0,
                       "sym": {}, "noon_sym": None, "noon_dist": 1e9}
            order.append(d)
        dd = days[d]
        t = inst_of(e)
        if t is not None:
            dd["tmin"] = min(dd["tmin"], t); dd["tmax"] = max(dd["tmax"], t)
        p = _met_precip(e)
        dd["precip"] += p; dd["n"] += 1
        if p > 0.2:
            dd["wet"] += 1
        sym = ((e["data"].get("next_6_hours") or {}).get("summary", {})
               .get("symbol_code") or (e["data"].get("next_12_hours") or {})
               .get("summary", {}).get("symbol_code") or "")
        if sym:
            dd["sym"][sym] = dd["sym"].get(sym, 0) + 1
        hr = _npt_hour(e["time"])
        if hr is not None and abs(hr - 12) < dd["noon_dist"]:
            dd["noon_dist"] = abs(hr - 12); dd["noon_sym"] = sym
    daily = {"time": [], "weather_code": [], "temperature_2m_max": [],
             "temperature_2m_min": [], "precipitation_sum": [],
             "precipitation_probability_max": []}
    for d in order[:7]:
        dd = days[d]
        sym = dd["noon_sym"] or (max(dd["sym"], key=dd["sym"].get) if dd["sym"] else "")
        daily["time"].append(d)
        daily["weather_code"].append(_met_wmo(sym))
        daily["temperature_2m_max"].append(round(dd["tmax"], 1) if dd["tmax"] > -1e8 else None)
        daily["temperature_2m_min"].append(round(dd["tmin"], 1) if dd["tmin"] < 1e8 else None)
        daily["precipitation_sum"].append(round(dd["precip"], 1))
        daily["precipitation_probability_max"].append(
            round(100 * dd["wet"] / dd["n"]) if dd["n"] else 0)
    return {"city": city, "current": cur, "daily": daily,
            "data_label": "live", "provider": "MET Norway"}

def inst_of(e):
    try:
        return e["data"]["instant"]["details"].get("air_temperature")
    except (KeyError, TypeError):
        return None

def _met_precip(e):
    d1 = (e["data"].get("next_1_hours") or {}).get("details", {})
    if "precipitation_amount" in d1:
        return float(d1["precipitation_amount"] or 0)
    d6 = (e["data"].get("next_6_hours") or {}).get("details", {})
    return float(d6.get("precipitation_amount", 0) or 0) / 6.0

def _npt_hour(iso_ts):
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo("Asia/Kathmandu")
    except Exception:  # noqa: BLE001
        from datetime import timedelta
        tz = timezone(timedelta(hours=5, minutes=45))
    dt = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(tz).hour

async def _fetch_weather_openmeteo():
    lats = ",".join(str(c["lat"]) for c in DISTRICTS)
    lons = ",".join(str(c["lon"]) for c in DISTRICTS)
    url = ("https://api.open-meteo.com/v1/forecast?latitude=" + lats + "&longitude=" + lons +
           "&current=temperature_2m,relative_humidity_2m,precipitation,weather_code,wind_speed_10m"
           "&daily=weather_code,temperature_2m_max,temperature_2m_min,precipitation_sum,"
           "precipitation_probability_max&timezone=Asia%2FKathmandu&forecast_days=7")
    async with _make_client(25) as client:
        resp = await _get_with_retry(client, url)
        raw = resp.json()
    data = raw if isinstance(raw, list) else [raw]
    out = {}
    for city, w in zip(DISTRICTS, data):
        out[city["id"]] = {"city": city, "current": w.get("current", {}),
                           "daily": w.get("daily", {}), "data_label": "live",
                           "provider": "Open-Meteo"}
    return out

async def _fetch_weather_met():
    sem = asyncio.Semaphore(10)
    async with _make_client(60) as client:
        async def one(city):
            async with sem:
                return await _fetch_met_city(client, city)
        results = await asyncio.gather(*(one(c) for c in DISTRICTS))
    return {w["city"]["id"]: w for w in results}

async def fetch_weather():
    """Live forecast for all monitored cities.
    Primary: Open-Meteo (free, no key). Fallback: MET Norway Locationforecast
    (free, no key) — needed because Open-Meteo rate-limits some shared cloud IPs."""
    async with _lock("weather"):
        hit = cache_get("weather")
        if hit is not None:
            return hit, True
        last_err = None
        for fetcher in (_fetch_weather_openmeteo, _fetch_weather_met):
            try:
                out = await fetcher()
                cache_set("weather", out, 3600)   # hourly: weather changes slowly
                _stale["weather"] = out
                return out, False
            except Exception as e:  # noqa: BLE001
                last_err = e
        if "weather" in _stale:                   # graceful degradation
            return _stale["weather"], True
        raise RuntimeError(f"all weather providers unreachable: {last_err}")

async def fetch_nemrc():
    """LIVE Nepal earthquake catalog scraped from the National Earthquake
    Monitoring & Research Centre (NEMRC), seismonepal.gov.np.
    Server-rendered table — no API key needed. Cached 30 min."""
    async with _lock("nemrc"):
        hit = cache_get("nemrc")
        if hit is not None:
            return hit, True
        url = "https://seismonepal.gov.np/ne/earthquakes"
        try:
            async with _make_client(25) as client:
                resp = await _get_with_retry(client, url)
                html = resp.text
        except Exception:
            if "nemrc" in _stale:
                return _stale["nemrc"], True
            raise
        quakes = []
        for row in re.findall(r'<tr[^>]*>(.*?)</tr>', html, re.S):
            cells = [re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', '', c)).strip()
                     for c in re.findall(r'<t[dh][^>]*>(.*?)</t[dh]>', row, re.S)]
            if len(cells) < 7:
                continue
            m_date = re.search(r'ई\.सं\.:\s*(\d{4}-\d{2}-\d{2})', cells[1])
            m_time = re.search(r'UTC:\s*([\d:]{8})', cells[2])
            m_mag = re.search(r'([\d.]+)\s*ML', cells[5])
            try:
                lat, lon = float(cells[3]), float(cells[4])
            except ValueError:
                continue
            if not (m_date and m_time and m_mag):
                continue
            try:
                dt = datetime.strptime(m_date.group(1) + " " + m_time.group(1),
                                       "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
            except ValueError:
                continue
            quakes.append({
                "id": f"nemrc-{m_date.group(1)}-{m_time.group(1)}-{cells[6]}",
                "mag": float(m_mag.group(1)), "mag_type": "ML",
                "place": cells[6], "place_ne": cells[6],
                "time": dt.isoformat(), "lat": lat, "lon": lon,
                "depth_km": None, "in_nepal": in_nepal(lat, lon),
                "dist_to_kathmandu_km": round(haversine_km(lat, lon, 27.7172, 85.3240), 1),
                "source": "NEMRC", "data_label": "live",
            })
        quakes.sort(key=lambda q: q["time"], reverse=True)
        cache_set("nemrc", quakes, 1800)
        _stale["nemrc"] = quakes
        return quakes, False

# ------------------------------------------------- DHM river gauges (live) --
# DHM's hydrology.gov.np pushes real-time river/rainfall data over socket.io
# (engine.io polling) at /gss/socket.io — events "river_watch"/"rainfall_watch".
# Implemented with plain httpx (no extra dependency); works wherever plain
# HTTPS POSTs are allowed.
DHM_WS = "https://hydrology.gov.np/gss/socket.io/"

def _eio_parse(txt):
    pkts, i = [], 0
    while i < len(txt):
        m = re.match(r'(\d+):', txt[i:])
        if not m:
            break
        ln = int(m.group(1)); j = i + len(m.group(0))
        pkts.append(txt[j:j + ln]); i = j + ln
    return pkts

def _eio_frame(pkt):
    return f"{len(pkt)}:{pkt}"

def _station_name(s):
    for k in ("stationName", "name", "station_name", "title", "station"):
        if s.get(k):
            return str(s[k])
    return str(s.get("stationIndex", "?"))

def _station_level(s):
    wl = s.get("waterLevel")
    if isinstance(wl, dict):
        v = wl.get("value")
    else:
        v = wl
    if v in (None, "", "N/A"):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None

def _norm_station(s):
    lat = s.get("latitude", s.get("lat")); lon = s.get("longitude", s.get("lon"))
    try:
        lat, lon = float(lat), float(lon)
    except (TypeError, ValueError):
        lat = lon = None
    status = str(s.get("status", "")).upper()
    level = "danger" if "DANGER" in status else "warning" if "WARNING" in status else "normal"
    wl = _station_level(s)
    suspect = wl is not None and wl > 100  # faulty sensor (e.g. 100008.5 m seen live)
    if suspect:
        wl = None
    return {"name": _station_name(s), "station_index": s.get("stationIndex"),
            "lat": lat, "lon": lon, "water_level": wl,
            "sensor_suspect": suspect,
            "status": status or "UNKNOWN", "level": level,
            "trend": s.get("steady"), "district": s.get("district"),
            "basin": s.get("basin"), "river": s.get("river"),
            "warning_level": s.get("warning_level"), "danger_level": s.get("danger_level"),
            "data_label": "live", "source": "DHM hydrology.gov.np"}

async def _dhm_ws_fetch(want=("river_test", "rainfall_watch", "river_discharge")):
    """socket.io client (polling → websocket upgrade) against DHM's feed.
    Collects every event the server emits after our client_request."""
    import socketio
    sio = socketio.AsyncClient(reconnection=False)
    got = {}
    stop = asyncio.Event()

    @sio.event
    async def connect():
        for ev in want:
            await sio.emit("client_request", ev)

    @sio.on("*")
    async def _catch(event, data):
        if event in ("connect", "disconnect"):
            return
        got[event] = data
        if len(got) >= 3:
            stop.set()

    try:
        await sio.connect("https://hydrology.gov.np", socketio_path="/gss/socket.io",
                          wait_timeout=20)
        try:
            await asyncio.wait_for(stop.wait(), timeout=25)
        except asyncio.TimeoutError:
            pass
    finally:
        try:
            await sio.disconnect()
        except Exception:  # noqa: BLE001
            pass
    return got

async def fetch_dhm_rivers():
    """Live DHM river gauge readings. Cached 15 min."""
    async with _lock("dhm"):
        hit = cache_get("dhm")
        if hit is not None:
            return hit, True
        try:
            ev = await _dhm_ws_fetch()
        except Exception:
            if "dhm" in _stale:
                return _stale["dhm"], True
            raise
        def _pick(*names):
            for n in names:
                v = ev.get(n)
                if isinstance(v, list) and v:
                    return v
            # fallback: first list-of-dicts payload from any event
            for v in ev.values():
                if isinstance(v, list) and v and isinstance(v[0], dict):
                    return v
            return []
        raw = _pick("river_test", "river_watch", "river", "rivers")
        stations = [_norm_station(s) for s in raw if isinstance(s, dict)]
        if not stations:
            # Never cache or label an empty feed as live — the WS gave nothing.
            raise RuntimeError(f"DHM feed connected but returned no station data (events: {sorted(ev.keys())})")
        rain = _pick("rainfall_watch", "rainfall_test", "rainfall", "rain")
        result = {"stations": stations, "station_count": len(stations),
                  "rainfall_stations": len(rain) if isinstance(rain, list) else 0,
                  "events_seen": sorted(ev.keys()),
                  "data_label": "live", "source": "DHM hydrology.gov.np"}
        cache_set("dhm", result, 900)
        _stale["dhm"] = result
        return result, False

# ------------------------------------------------------- incidents (GDACS) --
async def fetch_gdacs_nepal():
    """Real disaster events for Nepal from GDACS (free, no key). Cached 1h."""
    async with _lock("gdacs"):
        hit = cache_get("gdacs")
        if hit is not None:
            return hit, True
        try:
            async with _make_client(30) as client:
                resp = await _get_with_retry(
                    client, "https://www.gdacs.org/gdacsapi/api/events/geteventlist/SEARCH")
                feats = resp.json().get("features", [])
        except Exception:
            if "gdacs" in _stale:
                return _stale["gdacs"], True
            raise
        out = []
        for f in feats:
            p = f.get("properties", {}) or {}
            if "Nepal" not in str(p.get("country", "")):
                continue
            g = (f.get("geometry") or {})
            coords = g.get("coordinates") if isinstance(g, dict) else None
            urls = p.get("url") or {}
            out.append({
                "id": f"gdacs-{p.get('eventtype')}-{p.get('eventid')}",
                "event_type": p.get("eventtype"), "name": p.get("name"),
                "alert_level": p.get("alertlevel") or p.get("episodealertlevel"),
                "from": p.get("fromdate"), "to": p.get("todate"),
                "updated": p.get("datemodified"),
                "lon": coords[0] if coords else None, "lat": coords[1] if coords else None,
                "report_url": urls.get("report"),
                "data_label": "live", "source": "GDACS",
            })
        out.sort(key=lambda e: e["from"] or "", reverse=True)
        cache_set("gdacs", out, 3600)
        _stale["gdacs"] = out
        return out, False

# ------------------------------------------- satellite (Sentinel-2 OData) --
async def fetch_lake_scenes():
    """Latest low-cloud Sentinel-2 scene per priority lake (Copernicus OData,
    free, no key). Cached 6h — satellites revisit every ~5 days."""
    async with _lock("s2"):
        hit = cache_get("s2")
        if hit is not None:
            return hit, True
        out = []
        try:
            async with _make_client(40) as client:
                for lake in GLOF_LAKES:
                    scene = None
                    for cloud_max in (30, 60):
                        filt = ("Collection/Name eq 'SENTINEL-2' and "
                                f"OData.CSC.Intersects(area=geography'SRID=4326;POINT({lake['lon']} {lake['lat']})') and "
                                "Attributes/OData.CSC.DoubleAttribute/any(att:att/Name eq 'cloudCover' and "
                                f"att/OData.CSC.DoubleAttribute/Value lt {cloud_max})")
                        url = ("https://catalogue.dataspace.copernicus.eu/odata/v1/Products"
                               f"?$filter={quote(filt)}&$orderby=ContentDate/Start desc&$top=1")
                        try:
                            resp = await client.get(url)
                            resp.raise_for_status()
                            vals = resp.json().get("value", [])
                        except Exception:  # noqa: BLE001 — per-lake best effort
                            vals = []
                        if vals:
                            scene = vals[0]
                            break
                    if scene:
                        v = scene
                        out.append({"lake_id": lake["id"],
                                    "lake_en": lake["name_en"], "lake_ne": lake["name_ne"],
                                    "scene": v.get("Name", "")[:80],
                                    "sensed": (v.get("ContentDate") or {}).get("Start"),
                                    "data_label": "live",
                                    "source": "Copernicus Sentinel-2"})
                    else:
                        out.append({"lake_id": lake["id"], "lake_en": lake["name_en"],
                                    "lake_ne": lake["name_ne"], "scene": None,
                                    "note": "no low-cloud scene found", "data_label": "live",
                                    "source": "Copernicus Sentinel-2"})
        except Exception:
            if "s2" in _stale:
                return _stale["s2"], True
            raise
        cache_set("s2", out, 21600)
        _stale["s2"] = out
        return out, False

# ------------------------------------------------------- source probing ----
def flood_level(rain72):
    if rain72 >= 100: return 3
    if rain72 >= 50: return 2
    if rain72 >= 25: return 1
    return 0

def landslide_level(rain72, hill):
    if not hill: return 0
    if rain72 >= 80: return 3
    if rain72 >= 40: return 2
    if rain72 >= 20: return 1
    return 0

async def compute_risk():
    """Transparent heuristic risk engine — MODEL label, not an official forecast.

    Degrades gracefully: if the weather upstream is unreachable (rate-limited),
    flood/landslide show 'unknown' instead of failing the whole dashboard.
    """
    try:
        weather, _ = await fetch_weather()
    except Exception:
        weather = None
    try:
        quakes, _ = await fetch_usgs()
    except Exception:
        quakes = []
    now = time.time()
    results = []
    for city in DISTRICTS:
        if weather and city["id"] in weather:
            w = weather[city["id"]]
            daily = w["daily"]
            precips = (daily.get("precipitation_sum") or [])[:3]
            rain72 = round(sum(p or 0 for p in precips), 1)
            probs = (daily.get("precipitation_probability_max") or [])[:3]
            prob72 = max([p or 0 for p in probs] or [0])
            fl, ls = flood_level(rain72), landslide_level(rain72, city["hill"])
            fcast = (daily.get("time") or [])[:7]
        else:
            rain72, prob72, fcast = None, None, []
            fl, ls = -1, -1  # unknown
        # seismic: M4.5+ within 300 km in last 30 days
        recent = [q for q in quakes
                  if haversine_km(q["lat"], q["lon"], city["lat"], city["lon"]) <= 300]
        if len(recent) >= 3: seis = 2
        elif len(recent) >= 1: seis = 1
        else: seis = 0
        known = [x for x in (fl, ls, seis) if x >= 0]
        overall = max(known) if known else -1
        def lvl(x): return "unknown" if x < 0 else LEVELS[x]
        results.append({
            "city": city, "rain_72h_mm": rain72, "rain_prob_max": prob72,
            "flood": lvl(fl), "landslide": lvl(ls), "seismic": lvl(seis),
            "overall": lvl(overall),
            "overall_ne": "अज्ञात" if overall < 0 else LEVEL_NE[LEVELS[overall]],
            "recent_quakes_300km": len(recent),
            "forecast_dates": fcast,
            "weather_available": weather is not None,
            "data_label": "model",
            "computed_at": datetime.fromtimestamp(now, tz=timezone.utc).isoformat(),
        })
    order = {"unknown": -1, "low": 0, "moderate": 1, "high": 2, "critical": 3}
    results.sort(key=lambda r: order.get(r["overall"], -1), reverse=True)
    return results

async def build_alerts():
    """Generate alerts from live data + heuristic thresholds."""
    risk = await compute_risk()
    quakes, _ = await fetch_usgs()
    alerts, n = [], 0
    for r in risk:
        city = r["city"]
        if r["rain_72h_mm"] is None:
            continue  # weather upstream down — no heuristic alerts this cycle
        for hazard, key in (("flood", "flood"), ("landslide", "landslide")):
            lvl = LEVELS.index(r[key])
            if lvl >= 2:  # high or critical
                n += 1
                sev = "warning" if lvl == 3 else "watch"
                alerts.append({
                    "id": f"{hazard}-{city['id']}-{n}",
                    "severity": sev, "hazard": hazard,
                    "area_en": city["name_en"], "area_ne": city["name_ne"],
                    "headline_en": f"{hazard.title()} {sev}: {city['name_en']} — {r['rain_72h_mm']} mm rain expected in 72h",
                    "headline_ne": f"{'बाढी' if hazard == 'flood' else 'पहिरो'} {'चेतावनी' if sev == 'warning' else 'निगरानी'}: {city['name_ne']} — ७२ घण्टामा {r['rain_72h_mm']} मिमि वर्षा",
                    "actions_en": ACTIONS[hazard]["en"], "actions_ne": ACTIONS[hazard]["ne"],
                    "issued_at": r["computed_at"], "source": "suraksha-heuristic",
                    "data_label": "model",
                })
    # earthquake alerts: M5.5+ inside Nepal in last 7 days (LIVE source)
    week_ago = time.time() - 7 * 86400
    for q in quakes:
        qt = datetime.fromisoformat(q["time"]).timestamp()
        if q["in_nepal"] and (q["mag"] or 0) >= 5.5 and qt >= week_ago:
            n += 1
            alerts.append({
                "id": f"earthquake-{q['id']}", "severity": "warning", "hazard": "earthquake",
                "area_en": q["place"] or "Nepal", "area_ne": "नेपाल",
                "headline_en": f"Earthquake M{q['mag']}: {q['place']}",
                "headline_ne": f"भूकम्प M{q['mag']}: {q['place']}",
                "actions_en": ACTIONS["earthquake"]["en"], "actions_ne": ACTIONS["earthquake"]["ne"],
                "issued_at": q["time"], "source": "usgs-live", "data_label": "live",
                "usgs_url": q["url"],
            })
    order = {"emergency": 0, "warning": 1, "watch": 2, "advisory": 3}
    alerts.sort(key=lambda a: order.get(a["severity"], 9))
    return alerts

# ------------------------------------------------------------- messaging ----
class BroadcastIn(BaseModel):
    channel: str = "sms"          # sms | whatsapp | push
    area_en: str = "Kathmandu"
    message_en: str
    message_ne: str = ""

async def dispatch_broadcast(body: BroadcastIn):
    """Alert dissemination adapter. Console provider in prototype;
    set MESSAGING_API_URL + MESSAGING_API_KEY to forward to the real
    unified messaging API (POST /v1/messages)."""
    url = os.environ.get("MESSAGING_API_URL")
    key = os.environ.get("MESSAGING_API_KEY")
    payload = {"channel": body.channel, "area": body.area_en,
               "message_en": body.message_en, "message_ne": body.message_ne}
    if url and key:
        try:
            async with _make_client(15) as client:
                resp = await client.post(url.rstrip("/") + "/v1/messages",
                                         json=payload,
                                         headers={"Authorization": f"Bearer {key}"})
                return {"status": "forwarded", "provider_status": resp.status_code,
                        "data_label": "live"}
        except Exception as e:  # noqa: BLE001 — prototype adapter
            return {"status": "provider_error", "detail": str(e)[:200],
                    "data_label": "live"}
    print(f"[suraksha-broadcast:{body.channel}] {body.area_en} :: {body.message_en}")
    return {"status": "simulated",
            "note": "Console provider — set MESSAGING_API_URL/KEY for real dispatch",
            "echo": payload, "data_label": "sample"}

# ------------------------------------------------------------------- app ----
app = FastAPI(title="Suraksha API", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"],
                   allow_headers=["*"])

static_dir = os.path.join(BASE_DIR, "static")
if os.path.isdir(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

@app.get("/")
def index():
    return FileResponse(os.path.join(static_dir, "index.html"))

@app.get("/api/health")
def health():
    return {"status": "ok", "service": "suraksha", "version": "0.2.0",
            "time": datetime.now(timezone.utc).isoformat()}

@app.get("/api/districts")
@app.get("/api/cities")
def districts():
    return {"districts": DISTRICTS, "cities": DISTRICTS, "data_label": "live"}

@app.get("/api/earthquakes")
async def earthquakes(days: int = Query(30, ge=1, le=30),
                      min_magnitude: float = Query(4.5, ge=0),
                      nepal_only: bool = False):
    try:
        quakes, cached = await fetch_usgs()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"USGS unreachable: {str(e)[:150]}")
    cutoff = time.time() - days * 86400
    out = [q for q in quakes
           if (q["mag"] or 0) >= min_magnitude
           and datetime.fromisoformat(q["time"]).timestamp() >= cutoff
           and (not nepal_only or q["in_nepal"])]
    return {"count": len(out), "earthquakes": out[:500], "cached": cached,
            "source": "USGS Earthquake Hazards Program", "data_label": "live"}

@app.get("/api/weather")
async def weather(city: str = Query("kathmandu"), district: str = Query(None)):
    key = district or city
    try:
        data, cached = await fetch_weather()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"Weather unreachable: {str(e)[:150]}")
    if key not in data:
        raise HTTPException(404, f"Unknown district '{key}'")
    w = data[key]
    return {"city": w["city"], "district": w["city"], "current": w["current"], "daily": w["daily"],
            "cached": cached, "source": w.get("provider", "Open-Meteo"), "data_label": "live"}

@app.get("/api/weather/all")
async def weather_all():
    """All monitored cities in one response (one upstream call)."""
    try:
        data, cached = await fetch_weather()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"Weather unreachable: {str(e)[:150]}")
    return {"cities": list(data.values()), "cached": cached,
            "source": "Open-Meteo", "data_label": "live"}

@app.get("/api/risk")
async def risk():
    try:
        results = await compute_risk()
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"Risk engine failed: {str(e)[:150]}")
    return {"cities": results,
            "method": "heuristic thresholds on 72h forecast precipitation — prototype, not an official forecast",
            "data_label": "model"}

@app.get("/api/alerts")
async def alerts():
    try:
        items = await build_alerts()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"Alert engine failed: {str(e)[:150]}")
    return {"count": len(items), "alerts": items}

@app.get("/api/glof/lakes")
def glof_lakes():
    return {"count": len(GLOF_LAKES), "lakes": GLOF_LAKES,
            "notice": "Curated from the ICIMOD + UNDP + Government of Nepal 2026 PDGL assessment; coordinates marked approximate where noted"}

@app.get("/api/glof/summary")
def glof_summary():
    return GLOF_SUMMARY

@app.get("/api/earthquakes/nepal")
async def earthquakes_nepal():
    """Nepal's own seismic catalog (NEMRC) — catches smaller local events USGS misses."""
    try:
        quakes, cached = await fetch_nemrc()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"NEMRC unreachable: {str(e)[:150]}")
    return {"count": len(quakes), "earthquakes": quakes[:200], "cached": cached,
            "source": "National Earthquake Monitoring & Research Centre (NEMRC), Nepal",
            "data_label": "live"}

@app.get("/api/rivers")
async def rivers():
    """Live DHM river gauge readings (hydrology.gov.np real-time feed)."""
    try:
        data, cached = await fetch_dhm_rivers()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"DHM river feed unreachable: {str(e)[:150]}")
    return {**data, "cached": cached}

@app.get("/api/incidents")
async def incidents():
    """Real disaster events affecting Nepal (GDACS, free, no key)."""
    try:
        events, cached = await fetch_gdacs_nepal()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"GDACS unreachable: {str(e)[:150]}")
    return {"count": len(events), "incidents": events, "cached": cached,
            "data_label": "live"}

@app.get("/api/glof/satellite")
async def glof_satellite():
    """Latest low-cloud Sentinel-2 scene per priority lake (Copernicus, free)."""
    try:
        scenes, cached = await fetch_lake_scenes()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"Copernicus unreachable: {str(e)[:150]}")
    return {"count": len(scenes), "scenes": scenes, "cached": cached,
            "note": "Scene metadata (latest clear view). Pixel-level NDWI change detection = v2 roadmap.",
            "data_label": "live"}

@app.get("/api/sources/status")
async def sources_status():
    """Reachability of every upstream, probed from THIS server (production truth)."""
    probes = {
        "usgs": "https://earthquake.usgs.gov/fdsnws/event/1/query?format=geojson&limit=1",
        "open_meteo": "https://api.open-meteo.com/v1/forecast?latitude=27.7&longitude=85.3&current=temperature_2m",
        "met_norway": "https://api.met.no/weatherapi/locationforecast/2.0/compact?lat=27.7&lon=85.3",
        "nemrc": "https://seismonepal.gov.np/ne/earthquakes",
        "gdacs": "https://www.gdacs.org/gdacsapi/api/events/geteventlist/SEARCH",
        "copernicus": "https://catalogue.dataspace.copernicus.eu/odata/v1/Products?$top=1",
        "bipad": "https://bipad.gov.np/api/v1/",
        "dhm_ws": "https://hydrology.gov.np/gss/socket.io/?EIO=4&transport=polling",
    }
    out = {}
    async with _make_client(20) as client:
        for name, url in probes.items():
            t0 = time.time()
            try:
                headers = {"User-Agent": "Suraksha/0.2"} if name == "met_norway" else None
                r = await client.get(url, headers=headers)
                out[name] = {"reachable": r.status_code < 500,
                             "http": r.status_code,
                             "ms": int((time.time() - t0) * 1000)}
            except Exception as e:  # noqa: BLE001
                out[name] = {"reachable": False, "error": str(e)[:120],
                             "ms": int((time.time() - t0) * 1000)}
    return {"sources": out, "checked_at": datetime.now(timezone.utc).isoformat()}

@app.get("/api/shelters")
def shelters():
    return {"count": len(SHELTERS), "shelters": SHELTERS,
            "notice": "83 open spaces designated by IOM + Ministry of Home Affairs (2013), Nepal Gazette; coordinates approximate"}

@app.get("/api/overview")
async def overview():
    try:
        alerts_list = await build_alerts()
    except Exception:
        alerts_list = []
    try:
        quakes, _ = await fetch_usgs()
    except Exception:
        quakes = []
    try:
        nemrc, _ = await fetch_nemrc()
    except Exception:
        nemrc = []
    by_sev = {}
    for a in alerts_list:
        by_sev[a["severity"]] = by_sev.get(a["severity"], 0) + 1
    return {"alerts_by_severity": by_sev,
            "active_alerts": len(alerts_list),
            "earthquakes_30d_m45": len(quakes),
            "earthquakes_nemrc": len(nemrc),
            "districts_monitored": len(DISTRICTS),
            "glof_lakes_watched": len(GLOF_LAKES)}

@app.post("/api/broadcast")
async def broadcast(body: BroadcastIn):
    return await dispatch_broadcast(body)

async def _refresh_loop():
    await asyncio.sleep(60)  # let cold-start traffic settle first
    while True:
        try:
            await fetch_usgs(); await fetch_weather(); await fetch_nemrc()
        except Exception:  # noqa: BLE001 — background best-effort
            pass
        await asyncio.sleep(900)

@app.on_event("startup")
async def startup():
    asyncio.create_task(_refresh_loop())
