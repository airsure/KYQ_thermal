$DEBUG
C-------热管换热器主程序-------------------------------	
        DIMENSION XH(7),XC(7),X(7)
	CHARACTER FILENAME*22
	CHARACTER BILENAM1*22,BNO*22
	COMMON PROPA(55,7)
        COMMON /UNIT/IU
	COMMON /NAME/FILENAME
	COMMON /COM1/DO,DI,ST,SL,SL1,IB,IM,BL,N,FLMD,QC
C
	FILENAME='INB.DAT'	
	CALL LOADP2(0,0,7)
        READ(5,900)VFH,PFH
        READ(5,901)TFJH,TFCH
        READ(5,902)ALH,HFH,DRTAFH,SFH
        READ(5,903)DO,DI,ST,SL
        READ(5,904)(XH(I),I=1,7)
        READ(5,900)VFC,PFC
        READ(5,901)TFJC,TFCC
        READ(5,902)ALC,HFC,DRTAFC,SFC
        READ(5,904)(XC(I),I=1,7)
	READ(5,905)WN,FLMD,TLMD,RYH,RYC,HZF,HLZ
	READ(5,906)IBH,IMH,KT
C
25	CALL FPROP(PFH,TFJH,TFCH,XH,WMH,CPH,ROH,VISH,CLMDH,PRH)
        QH=VFH*WMH/22.4*CPH*(TFJH-TFCH)
	QC=QH*.97
	QC1=QC*.97
C
30	CALL FPROP(PFC,TFJC,TFCC,XC,WMC,CPC,ROC,VISC,CLMDC,PRC)
        QC2=VFC*WMC/22.4*CPC*(TFCC-TFJC)
        DQ=(QC1-QC2)/QC1
        IF(ABS(DQ).LE..01) GOTO 800
        TFCC=TFCC+DQ*(TFCC-TFJC)
        GOTO 30
C
800	IF(TFJH.GT.TFCC) GOTO 801
	TFCH=TFJH*.05+TFCH*.95
	GOTO 25
801	DT1=TFJH-TFCC
	DT2=TFCH-TFJC
	DTMAX=AMAX1(DT1,DT2)
	DTMIN=AMIN1(DT1,DT2)
	DTM=(DTMAX-DTMIN)/ALOG(DTMAX/DTMIN)
C
	AEXH=VFH/22.4*WMH/ROH/3600./WN
	EH=AEXH/(ALH/1000.)
	B=EH/(ST/1000.)
	IB=INT(B+1.)
	IF(KT.NE.1) GOTO 40
	IB=IBH
40	EH1=IB*1.*ST/1000.
C
	CALL AHFA(HFH,DRTAFH,SFH,ALH,VFH,WMH,VISH,ROH,CLMDH,
     &  PRH,GMAXH,WWH,REH,AHFH)
	CALL AHFA(HFC,DRTAFC,SFC,ALC,VFC,WMC,VISC,ROC,CLMDC,
     &  PRC,GMAXC,WWC,REC,AHFC)
        CALL AHFE(AHFH,HFH,DRTAFH,SFH,HFEH,AHH)
        CALL AHFE(AHFC,HFC,DRTAFC,SFC,HFEC,AHC)
C
        RW=(DO-DI)*.5/1000./TLMD
        DM=(DO+DI)*.5/1000.
        AW=3.14159*DM
        AI=3.14159*DI/1000.
C
        U=1./HFEH+RYH+RW*AHH/AW+1./HZF*AHH/AI+1./HLZ*AHH*ALH/(AI*ALC)
     &	+RW*AHH*ALH/(AW*ALC)+RYC*AHH/AHC+1./HFEC*AHH/AHC
        UFH=1./U
C
        AHHH=QC/UFH/DTM/3.6
        BN=AHHH/AHH/(ALH/1000.)
        BM=BN/IB
        IM=INT(BM+1)
	bno='设计计算'
C
	IF(KT.NE.1) GOTO 64
	AHH1=AREA(DO,HFH,DRTAFH,SFH)
	AHH1=AHH1*(IBH*IMH-INT(IMH/2))*ALH/1000.
	DAHH=(AHHH-AHH1)/AHH1
	IF(ABS(DAHH).LT..005) GOTO 65
	TFCH=TFCH-DAHH*(TFCH-TFJH)*.1
	GOTO 25
65	IM=IMH
	BNO='校核计算'
64	N=IB*IM-INT(IM/2)
	AHHH=AHH*(ALH/1000.)*N
C
	CALL DETP(-1,HFH,DRTAFH,SFH,AHH,GMAXH,RYH,
     &	TFJH,TFCH,HFEH,ALH,PFH,XH,VISH,ROH,DPH)
	CALL DETP(1,HFC,DRTAFC,SFC,AHC,GMAXC,RYC,
     &	TFJC,TFCC,HFEC,ALC,PFC,XC,VISC,ROC,DPC)
c
	WRITE(*,*)'  请输入计算标识：'
c	READ(*,910)BNO
	WRITE(*,*)'  请输入计算结果文件名：'
c	READ(*,910)BILENAM1
	BILENAM1='OUT.DAT'
	OPEN(6,FILE=BILENAM1,STATUS='NEW')
	WRITE(6,*)BNO,'热管式气-气换热器设计计算'
	WRITE(6,*)'--------------------------------------------------'
	WRITE(6,*)'序号        名称             单位         数值'
	WRITE(6,*)'--------------------------------------------------'
	WRITE(6,911)'   1   热侧气体流量          Nm^3/h ',VFH
	WRITE(6,911)'   2   热侧气体压力(绝压)   kgf/cm^2',PFH
	WRITE(6,911)'   3   热侧气体进口温度  　　  ℃   ',TFJH
	WRITE(6,911)'   4   热侧气体出口温度        ℃   ',TFCH
	WRITE(6,911)'   5   冷侧气体流量          Nm^3/h ',VFC
	WRITE(6,911)'   6   冷侧气体压力(绝压)   kgf/cm^2',PFC
	WRITE(6,911)'   7   冷侧气体进口温度  　　  ℃   ',TFJC
	WRITE(6,911)'   8   冷侧气体出口温度        ℃   ',TFCC
	WRITE(6,911)'   9   光管外径                mm   ',DO
	WRITE(6,911)'  10   光管内径                mm   ',DI
	WRITE(6,911)'  11   横向节距  　　          mm   ',ST
	WRITE(6,911)'  12   纵向节距                mm   ',SL1
	WRITE(6,911)'  13   热侧换热段长度          mm   ',ALH
	WRITE(6,911)'  14   热侧翅片高度            mm   ',HFH
	WRITE(6,911)'  15   热侧翅片厚度  　　      mm   ',DRTAFH
	WRITE(6,911)'  16   热侧翅片节距            mm   ',SFH
	WRITE(6,911)'  17   冷侧换热段长度          mm   ',ALC
	WRITE(6,911)'  18   冷侧翅片高度            mm   ',HFC
	WRITE(6,911)'  19   冷侧翅片厚度  　　      mm   ',DRTAFC
	WRITE(6,911)'  20   冷侧翅片节距            mm   ',SFC
	WRITE(6,911)'  21   热侧气体放热量         kJ/h  ',QH
	WRITE(6,911)'  22   传热量                 kJ/h  ',QC
	WRITE(6,911)'  23   冷侧气体吸热量  　　   kJ/h  ',QC1
	WRITE(6,911)'  24   平均温压                ℃   ',DTM
	WRITE(6,911)'  25   热侧气体流速            m/s  ',WWH
	WRITE(6,911)'  26   冷侧气体流速            m/s  ',WWC
	WRITE(6,911)'  27   热侧雷诺数  　　             ',REH
	WRITE(6,911)'  28   冷侧雷诺数  　　             ',REC
	WRITE(6,911)'  29   热侧换热系数          w/m^2℃',HFEH
	WRITE(6,911)'  30   冷侧换热系数          w/m^2℃',HFEC
	WRITE(6,911)'  31   传热系数              w/m^2℃',UFH
	WRITE(6,911)'  32   热侧换热面积            m^2  ',AHHH
	WRITE(6,912)'  33   迎风面换热管根数        根   ',IB
	WRITE(6,912)'  34   换热管排数              排   ',IM
	WRITE(6,912)'  35   换热管根数              根   ',N
	WRITE(6,911)'  36   换热器横向宽度          mm   ',EH1
	WRITE(6,911)'  37   换热器纵向长度          mm   ',BL
	WRITE(6,911)'  38   热侧气体压降            Pa   ',DPH
	WRITE(6,911)'  39   冷侧气体压降            Pa   ',DPC
C
900     FORMAT(F12.1,F8.2)
901     FORMAT(2F8.1)
902     FORMAT(F7.1,3F5.1)
903	FORMAT(2F5.1,2F6.1)
904	FORMAT(7F6.2)
905	FORMAT(F5.2,2F5.1,2F8.5,2F8.1)
906	FORMAT(3I5)
910     FORMAT(A22)
911	FORMAT(A36,F12.1)
912	FORMAT(A36,I10)
920     FORMAT(A10)
        STOP
        END
C
C-------子程序------------------------------------------
        SUBROUTINE FPROP(P,TJ,TC,X,WM,CP,RO,VIS,CLMD,PR)
        DIMENSION STRM(16),X(7)
	COMMON PROPA(55,7)
        COMMON /UNIT/IU
        DATA STRM/1.,7.,0.,0.,1.,11*0./
	WM=0.
	DO 10 I=1,7
        STRM(I+9)=X(I)/100.
	WRITE(*,*)'STRM10=',STRM(10)
        WM=WM+PROPA(10,I)*X(I)/100.
10	CONTINUE
        TP=(TJ+TC)/2.
        CALL IIU(STRM(3),STRM(4),TP,P)
        CALL HTCAP(STRM,CPAL,CP,IF1,IF2)
        CP=CP*4.1868/WM
	CALL DENSY(STRM,RL,RO,IF1,IF2)
        RO=RO*WM
	VIS=VISGM(STRM)*.1
	CLMD=CONGM(STRM)*3.6E-4*4.1868/3.6
	PR=CP*VIS/CLMD*1000.
	RETURN
	END
C
	SUBROUTINE AHFA(HF,DTA,SF,AL,VF,WM,VIS,RO,CLMD,PR,GMAX,
     &	WW,RE,AHF)
        COMMON /COM1/DO,DI,ST,SL,SL1,IB,IM,BL,N,FLMD,QC
	HNAF=((ST-DO)-2.*HF*DTA/SF)/1000.*AL/1000.*IB
	GMAX=VF/22.4*WM/HNAF
	WW=GMAX/RO/3600.
	RE=GMAX*DO/3600./1000./VIS
	HNU=.137*RE**.6338*PR**.3333
	AHF=1000.*CLMD/DO*HNU
	RETURN
	END
C
        SUBROUTINE AHFE(AHF,HF,DTA,SF,HFE,AH)
	COMMON /COM1/DO,DI,ST,SL,SL1,IB,IM,BL,N,FLMD,QC
        ZZ=HF/1000.*(2000.*AHF/FLMD/DTA)**.5
        YITA=TANH(ZZ)/ZZ*.9
        WRITE(*,*)'YITA=',YITA
	DF=DO+2.*HF
	AF=(2.*3.14159/4.*((DF/1000.)**2.-(DO/1000.)**2.)
     &	+3.14159*DF/1000.*DTA/1000.)*1000./SF
        AR=3.14159*DO/1000.*(1.-DTA/SF)
        AH=AF+AR
        HFE=AHF*(AR+YITA*AF)/AH
	END
C
	FUNCTION AREA(DO,HF,DTA,SF)
	COMMON /COM2/AF,AR
	DF=DO+2.*HF
	AF=(2.*3.14159/4.*((DF/1000.)**2.-(DO/1000.)**2.)
     &	+3.14159*DF/1000.*DTA/1000.)*1000./SF
        AR=3.14159*DO/1000.*(1.-DTA/SF)
        AREA=AF+AR
	RETURN
	END
C
	SUBROUTINE DETP(K,HF,DTA,SF,AH,GMAX,RY,
     &	TJ,TC,HFE,AL,P,X,VIS,RO,DP)
	DIMENSION STRM(16),X(7)
	COMMON PROPA(55,7)
        COMMON /UNIT/IU
	COMMON /COM1/DO,DI,ST,SL,SL1,IB,IM,BL,N,FLMD,QC
        DATA STRM/1.,7.,0.,0.,1.,11*0./
	DO 20 I=1,7
	STRM(9+I)=X(I)/100.
20      CONTINUE
	PI=3.1415926
	DF=DO+2.*HF
	SL1=(SL**2.-(ST/2.)**2.)**.5
	CNFV=ST*SL1/1000.**2.-PI/4.*(DO/1000.)**2.
     &  -PI/4.*((DF/1000.)**2.-(DO/1000.)**2.)*DTA/1000.*1000./SF
	DEV=4.*CNFV/AH
	REF=GMAX*DEV/3600./VIS
        WRITE(*,*)'REF=',REF
        F=1.92*1/REF**.145
        WRITE(*,*)'F=',F,N
	TP=.5*(TJ+TC)
	HFE1=1./(1./HFE+RY)
	TWB=TP+K*QC/(HFE1*AH*AL/1000.*N)/3.6
	WRITE(*,*)'TWB=',TWB,TP
        CALL IIU(STRM(3),STRM(4),TWB,P)	
	VIS1=VISGM(STRM)*.1
        BL=SL1*IM/1000.
        DP=F*(GMAX/3600)**2.*BL/2./9.8/DEV/RO/(VIS/VIS1)**.14
     &	*(DEV/(ST/1000.))**.4*(SL/ST)**.6*9.8
	RETURN
	END
