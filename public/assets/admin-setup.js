(function(){
  const $=id=>document.getElementById(id);
  $('setupForm').addEventListener('submit',async function(e){
    e.preventDefault();
    const key=$('key').value.trim(), user=$('user').value.trim(), pass=$('pass').value, pass2=$('pass2').value;
    $('msg').className='msg'; $('msg').textContent='';
    if(user.length<3||user.length>40){$('msg').className='msg err';$('msg').textContent='Username must be 3–40 characters.';return;}
    if(pass.length<12){$('msg').className='msg err';$('msg').textContent='Password must be at least 12 characters.';return;}
    if(pass!==pass2){$('msg').className='msg err';$('msg').textContent='Passwords do not match.';return;}
    const button=$('create'); button.disabled=true;
    try{
      const r=await fetch('/api/admin/setup',{method:'POST',headers:{'Content-Type':'application/json'},credentials:'same-origin',body:JSON.stringify({setup_key:key,username:user,password:pass})});
      const text=await r.text(); let d={}; try{d=text?JSON.parse(text):{}}catch(_){throw new Error('Server returned an invalid response ('+r.status+').');}
      if(!r.ok) throw new Error(d.error||('Setup failed ('+r.status+')'));
      $('msg').className='msg ok'; $('msg').textContent='Owner created. Opening admin…';
      setTimeout(()=>location.replace('/admin/'),500);
    }catch(err){$('msg').className='msg err';$('msg').textContent=err.message;}
    finally{button.disabled=false;}
  });
})();
