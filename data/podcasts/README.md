# תסריטי הפודקאסט

כאן יושבים התסריטים, לא הקבצי שמע.

`YYYY-MM-DD.script.md` הוא התסריט של הפרק לאותה מהדורה: שורות דיאלוג
מתחלפות של דנה ויונתן, ותו לא. הקבצים האלה **נשמרים בגיט**, כי הם התוצר
העריכתי. קובץ השמע הוא רק הקראה של תסריט שכבר אושר.

תסריט שנכתב ביד תקף בדיוק כמו טיוטה שנוצרה אוטומטית. אין רישום של מקורו.

```powershell
# טיוטה מתוך מחקר, ואז עצירה לקריאה
.\.venv\Scripts\python.exe scripts\podcast.py --date YYYY-MM-DD --source data\research\bank\slug.md

# בדיקת סגנון וחישוב אורך, בלי לשלם דבר
.\.venv\Scripts\python.exe scripts\podcast.py --date YYYY-MM-DD --dry-run

# הקלטה
.\.venv\Scripts\python.exe scripts\podcast.py --date YYYY-MM-DD --speak --upload
```

התדריך הקבוע לכתיבה נמצא ב-`prompts/podcast.md`. הכללים המלאים ב-`docs/SPEC.md` §5.1.

`_work/` הוא תיקיית ביניים של קטעי WAV בזמן ההרכבה, והיא מחוץ לגיט.
