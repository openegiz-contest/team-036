#!/usr/bin/env python3
"""OpenPit Twin simulator. Publishes all changing state through MQTT -> Eclipse Ditto."""
import os, json, time, random, signal, logging
import paho.mqtt.client as mqtt
NS="org.openegiz.openpit"; PREFIX="telemetry"
TICK=float(os.getenv("TICK_SECONDS","2")); SPEEDUP=float(os.getenv("SIM_SPEEDUP","20"))
SCENARIO=os.getenv("OPENPIT_SCENARIO","normal")  # normal | road_closure | excavator_failure
rng=random.Random(42); log=logging.getLogger("openpit")
class Truck:
 def __init__(self,i):
  self.id=f"truck-{i:02d}"; self.state="waiting_dispatch"; self.assigned="none"; self.pos=0.; self.payload=0.; self.fuel=rng.uniform(68,100); self.trips=0; self.wait=0.; self.timer=0.; self.route=1
 def feat(self):
  return {"state":{"value":self.state},"assigned_to":{"value":self.assigned},"payload":{"value":round(self.payload,1),"unit":"t"},"speed":{"value":round(self.speed,1),"unit":"km/h"},"route_position":{"value":round(self.pos,3),"unit":"km"},"fuel":{"value":round(self.fuel,1),"unit":"%"},"trips_total":{"value":self.trips,"unit":"trips"},"wait_minutes":{"value":round(self.wait,1),"unit":"min"}}
class Sim:
 def __init__(self):
  self.t=0.; self.ore=0.; self.idle=0.; self.trucks=[Truck(i) for i in range(1,7)]
  self.exc=[{"state":"loading","timer":0.,"loaded":0.,"queue":0,"idle":0.,"grade":0.68},{"state":"loading","timer":0.,"loaded":0.,"queue":0,"idle":0.,"grade":0.74}]
  self.dump=0.; self.dumpq=0
 def step(self,dt):
  self.t+=dt; queues=[0,0]
  # Dynamic dispatch: assign waiting truck to the excavator with lowest predicted queue/travel cost.
  for tr in self.trucks:
   if tr.state=="waiting_dispatch":
    costs=[]
    for j,e in enumerate(self.exc):
     road=j+1; penalty=18 if SCENARIO=="road_closure" and road==1 else 0
     penalty+=30 if SCENARIO=="excavator_failure" and j==0 else 0
     costs.append(e["queue"]*2.3 + (2.4 if j==0 else 3.1)*60/24 + penalty)
    j=min(range(2),key=lambda k:costs[k]); tr.assigned=f"excavator-{j+1:02d}"; tr.route=j+1; tr.state="to_loader"; tr.pos=0.; tr.speed=24.
   j=int(tr.assigned[-2:])-1 if tr.assigned!="none" else 0
   e=self.exc[j]
   if SCENARIO=="excavator_failure" and j==0 and tr.state in ("to_loader","loading"):
    # Cancel the assignment and return the truck to dispatch rather than leaving it stranded.
    tr.state="waiting_dispatch"; tr.assigned="none"; tr.speed=0.; tr.wait+=dt/60
   if tr.state=="to_loader":
    length=2.4 if tr.route==1 else 3.1
    speed=24 if tr.route==1 else 21
    if SCENARIO=="road_closure" and tr.route==1: speed*=0.45
    tr.speed=speed; tr.pos+=speed*dt/3600*SPEEDUP; tr.fuel-=speed*dt/3600*SPEEDUP*0.035
    if tr.pos>=length: tr.pos=0.; tr.state="loading"; tr.timer=0.; tr.payload=0.; e["queue"]=max(0,e["queue"]-1)
   elif tr.state=="loading":
    tr.speed=0.; tr.timer+=dt*SPEEDUP
    if SCENARIO=="excavator_failure" and j==0:
     tr.wait+=dt/60; e["idle"]+=dt/60
    elif tr.timer>=150:
     tr.payload=90.; tr.state="hauling"; tr.pos=0.; e["loaded"]+=90.; e["state"]="loading"
   elif tr.state=="hauling":
    tr.speed=22.; length=2.4 if tr.route==1 else 3.1; tr.pos+=tr.speed*dt/3600*SPEEDUP
    tr.fuel-=tr.speed*dt/3600*SPEEDUP*0.04
    if tr.pos>=length: tr.state="dumping"; tr.speed=0.; tr.timer=0.
   elif tr.state=="dumping":
    tr.timer+=dt*SPEEDUP
    if tr.timer>=45:
     self.ore+=tr.payload; self.dump+=tr.payload; tr.trips+=1; tr.payload=0.; tr.state="returning"; tr.pos=0.
   elif tr.state=="returning":
    length=2.4 if tr.route==1 else 3.1; tr.speed=32.; tr.pos+=tr.speed*dt/3600*SPEEDUP
    if tr.pos>=length: tr.state="waiting_dispatch"; tr.assigned="none"; tr.pos=0.
   if tr.state in ("loading","waiting_dispatch"): tr.wait+=dt/60
   if tr.fuel<12 and tr.state not in ("refuelling",): tr.state="refuelling"; tr.speed=0.; tr.timer=0.
   elif tr.state=="refuelling":
    tr.timer+=dt*SPEEDUP
    if tr.timer>=300: tr.fuel=95.; tr.state="waiting_dispatch"; tr.assigned="none"
  for j,e in enumerate(self.exc):
   e["queue"]=sum(1 for tr in self.trucks if tr.assigned==f"excavator-{j+1:02d}" and tr.state=="to_loader")
   if SCENARIO=="excavator_failure" and j==0: e["state"]="out_of_service"
   else: e["state"]="loading" if any(t.state=="loading" and t.assigned==f"excavator-{j+1:02d}" for t in self.trucks) else "idle"
 def message(self,features):
  return {"topic":f"{NS}/PLACEHOLDER/things/twin/commands/modify","path":"/features","value":features}
 def publish(self,c,thing,features):
  payload={"topic":f"{NS}:{thing}/things/twin/commands/modify","path":"/features","value":{k:{"properties":v} for k,v in features.items()}}
  c.publish(f"{PREFIX}/{thing}",json.dumps(payload),qos=1)
 def run(self):
  c=mqtt.Client(mqtt.CallbackAPIVersion.VERSION2); c.connect(os.getenv("MQTT_HOST","mosquitto"),int(os.getenv("MQTT_PORT","1883")),60); c.loop_start()
  log.info("OpenPit Twin running; scenario=%s",SCENARIO)
  while True:
   self.step(TICK)
   active=sum(t.state in ("to_loader","loading","hauling","dumping","returning") for t in self.trucks)
   for tr in self.trucks:self.publish(c,tr.id,tr.feat())
   for j,e in enumerate(self.exc):
    self.publish(c,f"excavator-{j+1:02d}",{"state":{"value":e["state"]},"queue_length":{"value":e["queue"],"unit":"trucks"},"face":{"value":"north" if j==0 else "south"},"grade":{"value":e["grade"],"unit":"% Cu"},"loaded_tonnes":{"value":round(e["loaded"],1),"unit":"t"},"idle_minutes":{"value":round(e["idle"],1),"unit":"min"}})
   for j in range(1,3):
    closed=SCENARIO=="road_closure" and j==1
    roadtrucks=sum(1 for t in self.trucks if t.route==j and t.state in ("to_loader","hauling","returning"))
    self.publish(c,f"road-{j:02d}",{"state":{"value":"closed" if closed else "open"},"traffic_factor":{"value":0.45 if closed else 1.0},"queue_trucks":{"value":roadtrucks,"unit":"trucks"},"travel_time_min":{"value":round((2.4 if j==1 else 3.1)*60/(24 if j==1 else 21)*(2.2 if closed else 1),1)}})
   self.publish(c,"dump-01",{"state":{"value":"available"},"throughput":{"value":round(self.ore/max(self.t/3600,0.01),1),"unit":"t/h"},"tonnes_total":{"value":round(self.ore,1),"unit":"t"},"queue_length":{"value":sum(t.state=="dumping" for t in self.trucks),"unit":"trucks"}})
   self.publish(c,"pit-01",{"ore_mined":{"value":round(self.ore,1),"unit":"t"},"active_trucks":{"value":active,"unit":"trucks"},"idle_minutes":{"value":round(sum(t.wait for t in self.trucks),1),"unit":"min"},"dispatch_mode":{"value":"road_closure" if SCENARIO=="road_closure" else ("failure_recovery" if SCENARIO=="excavator_failure" else "balanced")}})
   time.sleep(TICK)
if __name__=="__main__":
 logging.basicConfig(level=logging.INFO); Sim().run()
