  except sqlite3.IntegrityError:return False
 def insert_many(self,items:Iterable[NewsItem]):
  added=skipped=0
  for item in items:
   if self.insert(item):added+=1
   else:skipped+=1
  return added,skipped
 def count(self):return int(self.conn.execute("SELECT COUNT(*) AS count FROM news_items").fetchone()["count"] if self._postgres else self.conn.execute("SELECT COUNT(*) AS count FROM news_items").fetchone()[0])
 def latest(self,limit=20,category=None,status=None,search=None,review_status=None,instagram_status=None):
  clauses=[];params=[];ph="%s" if self._postgres else "?"
  for col,val in (("category",category),("status",status),("fact_check_status",review_status),("instagram_status",instagram_status)):
   if val and val!="all":clauses.append(f"{col} = {ph}");params.append(val)
  if search:clauses.append(f"(LOWER(title) LIKE LOWER({ph}) OR LOWER(summary) LIKE LOWER({ph}))");params.extend([f"%{search}%",f"%{search}%"])
  where=(" WHERE "+" AND ".join(clauses)) if clauses else ""; return self.conn.execute(f"SELECT * FROM news_items{where} ORDER BY id DESC LIMIT {ph}",(*params,limit)).fetchall()
 def update(self,item_id:int,**fields:Any):
  allowed={"title","summary","category","status","bot_summary","bot_article","ai_summary","ai_article","fact_check_status","fact_check_notes","image_url","approved_at","published_at_site","instagram_status","instagram_media_id","instagram_error","instagram_published_at","instagram_attempts","instagram_last_attempt_at","instagram_next_retry_at","instagram_scheduled_at","instagram_container_id","reel_cloudinary_public_id","instagram_selected","instagram_queue_order","public_source"}; fields={k:v for k,v in fields.items() if k in allowed}
  if not fields:return
  ph="%s" if self._postgres else "?";sets=[];params=[]
  for k,v in fields.items():sets.append(f"{k} = {ph}");params.append(v)
  params.append(item_id);self.conn.execute(f"UPDATE news_items SET {', '.join(sets)} WHERE id = {ph}",params)
  if not self._postgres:self.conn.commit()

 def log_activity(self,username,action,item_id=None,details=None):
  now=NewsItem.now_iso(); payload=str(details or "")[:4000];
  if self._postgres:self.conn.execute("INSERT INTO admin_activity (username,action,item_id,details,created_at) VALUES (%s,%s,%s,%s,%s)",(str(username),str(action),item_id,payload,now))
  else:self.conn.execute("INSERT INTO admin_activity (username,action,item_id,details,created_at) VALUES (?,?,?,?,?)",(str(username),str(action),item_id,payload,now)); self.conn.commit()
 def recent_activity(self,limit=50):
  try:
   limit=max(1,min(int(limit),200))
  except (TypeError,ValueError):
   limit=50
  ph="%s" if self._postgres else "?"
  return self.conn.execute(f"SELECT id,username,action,item_id,details,created_at FROM admin_activity ORDER BY id DESC LIMIT {ph}",(limit,)).fetchall()
 def next_instagram_queue_order(self):
  row=self.conn.execute("SELECT COALESCE(MAX(instagram_queue_order),0) AS value FROM news_items").fetchone(); return int(row["value"] if self._postgres else row[0])+1