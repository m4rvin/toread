from config import *
from PharosMessageManager import PharosMessageManager
from PharosNeighborManager import PharosNeighborManager
from PharosNCClient import PharosNCClient
from ping import whereis_newping
from ping import IcmpPinger
from Vivaldi.VivaldiNeighbor import *

from twisted.internet import reactor
from ping import PingClientIF
from gossip import GossipClient
from nc import NCClient
from coor.HeightCoordinate import *
from coor.EuclideanCoordinate import *
import socket
import sys


class PHAROS():
    def __init__(self):
        self.round = 0
        self.myClient = PharosNCClient()
        self.myNbManager = PharosNeighborManager()
        self.myMsgManager = PharosMessageManager()
        "initiate the nc of myClient"
        if PHAROS_USING_HEIGHT_GLOBAL:
            tmpCoor = HeightCoordinate( PHAROS_DIMENSION_GLOBAL )
        else:
            tmpCoor = EuclideanCoordinate( PHAROS_DIMENSION_GLOBAL )
        self.myClient.globalNC.set(MYIP, tmpCoor, 1.5)
        if PHAROS_USING_HEIGHT_LOCAL:
            tmpCoor = HeightCoordinate( PHAROS_DIMENSION_LOCAL )
        else:
            tmpCoor = EuclideanCoordinate( PHAROS_DIMENSION_LOCAL )        
        self.myClient.clusterNC.set(MYIP, tmpCoor, 1.5)        
        
        "this part checks whether myself is in the bootstrap list"
        clusterID = None
        clusterID = self.checkClusterBootStrap()
        "this part checks whether myself is in the landmark list"
        clusterkeys = PHAROS_LM.keys()
        for id in clusterkeys:
            if clusterID!=None:
                break
            lms = PHAROS_LM[id]
            for lm in lms:
                lmip = socket.gethostbyname(lm)
                if lmip==MYIP:
                    clusterID = id
                    print "The clusterID is assigned. This node is one of the landmark nodes"
                    print "ClusterID:",clusterID
                    break

        '''this part will find the cluster of the node'''
        if clusterID == None:
            clusternames = PHAROS_LM.keys()
            pingResult ={}
            for id in clusternames:
                lms = PHAROS_LM[id]
                pingResult[id] = 5000
                temp = []
                for lm  in lms:
                    lmip = socket.gethostbyname(lm)
                    try:
                        # use whereis ping, but we need sudo 
                        #res=int(whereis_newping.pingNode(alive=0, timeout=1.0, ipv6=0, number=3, node=lmip, flood=0, size=whereis_newping.ICMP_DATA_STR))
                        res = IcmpPinger.Ping(lmip)
                    except:
                        continue
                    temp.append(res)
                temp.remove(max(temp))
                temp.remove(min(temp))
                if len(temp)==0:
                    print "Error when locating the cluster ID:",id,"!\n Pharos will exit..."
                    sys.exit(1)
                pingResult[id] = float(sum(temp))/len(temp)
            minrtt = min(pingResult.values())
            # if minrtt is too large, this may means something wrong with icmp or network connection
            if minrtt>5000:
                print "Icmp pinger can not get the right value...\nPlease check the network connection or check whether icmp ping can be used on this host"
                print "PHAROS exit..."
                sys.exit(1)
            clusterID=""
            for id in clusternames:
                if pingResult[id]==minrtt:
                    clusterID = id
                    print "ClusterID is assigned after pinging all the landmarks..."
                    print "clusterID:",clusterID
                    break
        ''' we store the cluster info in clusterID'''
        self.myClient.clusterID = clusterID
        " initiate the bootstrap list according to the clusterID"
        clusterboot = CLUSTER_BOOTLIST[clusterID]
        for node in clusterboot:
            try:
                ip = socket.gethostbyname(node)
            except:
                continue
            if ip==MYIP:
                continue
            self.myNbManager.clusterNeighborMgr.addIP(ip)
        
        "initiate the boostrap list of the global overlay"
        for node in GLOBAL_BOOTLIST:
            try:
                ip = socket.gethostbyname(node)
            except:
                continue
            if ip==MYIP:
                continue
            self.myNbManager.globalNeighborMgr.addIP(ip)
            
        print "Initial global neighborlist length: ",self.myNbManager.globalNeighborMgr.getLength()
        print "Initial cluster neighborlist length: ",self.myNbManager.clusterNeighborMgr.getLength()
        
        self.mainloop()
        
    def checkClusterBootStrap(self):
        cboots = CLUSTER_BOOTLIST
        myname = socket.gethostname()
        for k in cboots.keys():
            tmpboots = cboots[k]
            for bh in tmpboots:
                if bh == myname:
                    print "local host is in the cluster Bootstrap, local host cluster ID is", k
                    return k
        return None
    
    def globalPingFinish(self,pingData):
        self.globalrtt = pingData.time
        print "ping global neighbor", self.globalNBIP,"The rtt is",self.globalrtt
        if self.globalrtt<PINGTIMEOUT/PINGNUM and self.globalrtt>0:
            NCDefer = NCClient.request("PharosBase",self.globalNBIP,NCPORT,NCTIMEOUT)
            NCDefer.addCallback(self.NCRecieved)  
        else:
            ret = self.myNbManager.removeGlobalNeighbor( self.globalNBIP )
            if ret:
                print "Delete", self.globalNBIP, "from global neighbor list."
            else:
                print "Error when Delete", self.globalNBIP, "from global neighbor list."
        return
    
    def localPingFinish(self,pingData):
        self.localrtt = pingData.time
        print "ping local neighbor",self.localNBIP,"The rtt is",self.localrtt
        if self.localrtt<PINGTIMEOUT/PINGNUM and self.localrtt>0:
            NCDefer = NCClient.request("PharosCluster",self.localNBIP,NCPORT,NCTIMEOUT)
            NCDefer.addCallback(self.NCRecieved)
        else:
            ret = self.myNbManager.removeClusterNeighbor( self.localNBIP )
            if ret:
                print "Delete", self.localNBIP, "from cluster neighbor list."
            else:
                print "Error when Delete", self.localNBIP, "from cluster neighbor list."
        return
        
    def GossipRecieved(self,gossipData):
        if DEBUG:
            print "[PHAROS] GossipRecieved function is called....."
            print "[PHAROS] The length of receieved gossipData:", len(gossipData.recv)
        #translate from messege
        gossipClientList = self.myMsgManager.decodeGossip(gossipData.recv)
        for eachClient in gossipClientList:
            tmpclient = eachClient["client"]
            if tmpclient.getIP()!=MYIP:
                if eachClient["nctype"]=="global":
                    self.myNbManager.globalNeighborMgr.addClient(tmpclient)
                    #print "========================================================"
                    print "global neighborlist length: ",self.myNbManager.globalNeighborMgr.getLength()
                    #print "global neighborlist details:",self.myNbManager.globalNeighborMgr.printNeighborList()
                    #self.myNbManager.globalNeighborMgr.printNeighborList()
                    #print "========================================================"
                if eachClient["nctype"]=="cluster":
                    if eachClient["clusterID"]!=self.myClient.clusterID:
                        print "Error when updating cluster overlay neighbors, the clusterID is different. Neighbor ip:",tmpclient.getIP()
                    else:
                        self.myNbManager.clusterNeighborMgr.addClient(tmpclient)
                    #print "========================================================"
                    print "cluster neighborlist length: ",self.myNbManager.clusterNeighborMgr.getLength()
                    #print "cluster neighborlist details:",self.myNbManager.clusterNeighborMgr.printNeighborList()
                    #self.myNbManager.clusterNeighborMgr.printNeighborList()
                    #print "========================================================"                    
        '''update neighbors'''
        return
    
    def NCRecieved(self,ncData):
        #translate from messege
        if DEBUG:
            print "[PHAROS] NCRecieved function is called....."    
            print "[PHAROS] NCRecieved data length:", len(ncData.recv)    
        targetInfo=self.myMsgManager.decodeOne(ncData.recv)
        targetClient = targetInfo["client"]
        if DEBUG:
            print "[PHAROS] the receieved object's nctypeprint :",targetInfo["nctype"]
        if targetInfo["nctype"]=="global":
            print "Update global:",targetClient.ip,",RTT=",self.globalrtt*1000
            targetNeighbor=self.myNbManager.globalNeighborMgr.getNeighbor(targetClient.ip)
            if targetNeighbor==None:
                targetNeighbor=VivaldiNeighbor(PHAROS_USING_HEIGHT_GLOBAL, PHAROS_DIMENSION_GLOBAL)
            targetNeighbor.setClient(targetClient)
            targetNeighbor.updateRTT(self.globalrtt)
            self.myNbManager.globalNeighborMgr.addClient(targetClient)
            self.myNbManager.globalNeighborMgr.update(targetNeighbor)
            if DEBUG:
                print "[PHAROS] Add global NB ",targetClient.ip
            #gossip
            gossipDefer = GossipClient.request("PharosBase",self.globalNBIP,GOSSIPPORT,GOSSIPTIMEOUT)
            gossipDefer.addCallback(self.GossipRecieved)
            #update
            self.myClient.globalNC.update(targetClient,self.globalrtt*1000) #Attention!self.rtt must be multiplied by 1000
        if targetInfo["nctype"]=="cluster":
            if targetInfo["clusterID"] != self.myClient.clusterID:
                print "Error in cluster NC update, remote host:",targetInfo
                removeret = self.myNbManager.removeClusterNeighbor( targetClient.getIP() )
                if removeret:
                    print "Delete", targetClient.getIP() ," from cluster neighbor list."
                else:
                    print "Error when delete", targetClient.getIP() ," from cluster neighbor list."
            else:
                print "Update local:",targetClient.ip,",RTT=",self.localrtt*1000
                targetNeighbor=self.myNbManager.clusterNeighborMgr.getNeighbor(targetClient.ip)
                if targetNeighbor==None:
                    targetNeighbor=VivaldiNeighbor(PHAROS_USING_HEIGHT_LOCAL, PHAROS_DIMENSION_LOCAL)
                targetNeighbor.setClient(targetClient)
                targetNeighbor.updateRTT(self.localrtt)
                self.myNbManager.clusterNeighborMgr.addClient(targetClient)
                self.myNbManager.clusterNeighborMgr.update(targetNeighbor)
                if DEBUG:
                    print "[PHAROS] Add cluster NB ",targetClient.ip
                #gossip
                gossipDefer = GossipClient.request("PharosCluster",self.localNBIP,GOSSIPPORT,GOSSIPTIMEOUT)
                gossipDefer.addCallback(self.GossipRecieved)
                #update
                self.myClient.clusterNC.update(targetClient,self.localrtt*1000) #Attention!self.rtt must be multiplied by 1000            
                
        return
    
    
    def mainloop(self):
        self.round = self.round + 1
        print "update times: "+str(self.round)
        print "global nc info:"
        self.myClient.globalNC.printInfo()
        print "local nc info:"
        self.myClient.clusterNC.printInfo()
        # copy update global here and test,    this still not work
        '''
        nbip = self.myNbManager.globalNeighborMgr.selectIP()
        print "global neighbor ip: ", nbip
        self.globalNBIP = nbip
        pingDefer = PingClientIF.ping(PINGMETHOD,nbip,PINGPORT,PINGTIMEOUT,PINGNUM,PINGBYTES)
        pingDefer.addCallback(self.globalPingFinish)         
        '''
        #self.updateGlobal()  # this can not work either
        reactor.callLater(0, self.updateGlobal)
        reactor.callLater(PHAROS_LOOP_TIME/2, self.updateLocal)
        reactor.callLater(PHAROS_LOOP_TIME, self.mainloop)
        
    def updateGlobal(self):
        nbip = self.myNbManager.globalNeighborMgr.selectIP()
        if DEBUG:
            print "global neighbor ip: "+nbip
        self.globalNBIP = nbip
        pingDefer = PingClientIF.ping(PINGMETHOD,nbip,PINGPORT,PINGTIMEOUT,PINGNUM,PINGBYTES)
        pingDefer.addCallback(self.globalPingFinish)    
        return
    
    def updateLocal(self):
        nbip = self.myNbManager.clusterNeighborMgr.selectIP()
        if DEBUG:
            print "cluster neighbor ip: "+nbip
        self.localNBIP = nbip
        pingDefer = PingClientIF.ping(PINGMETHOD,nbip,PINGPORT,PINGTIMEOUT,PINGNUM,PINGBYTES)
        pingDefer.addCallback(self.localPingFinish)           
        return
        
        
def start():
    global main 
    main = PHAROS()
        
        
            
                
                
        
        