# -*- coding: utf-8 -*-
"""
Created on Wed Sep 15 14:34:07 2021

@author: Jing
"""
import os
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib as mpl

from .ions import ions_WEIGHT, ions_CHARGE

# Define the plotting function
def plot(df, 
         unit='mg/L', 
         figname='contour-filled Piper diagram', 
         figformat='jpg'):
    """Plot the Piper diagram.
    
    Parameters
    ----------
    df : class:`pandas.DataFrame`
        Geochemical data to draw Gibbs diagram.
    unit : class:`string`
        The unit used in df. Currently only mg/L is supported. 
    figname : class:`string`
        A path or file name when saving the figure.
    figformat : class:`string`
        The file format, e.g. 'png', 'pdf', 'svg'
        
        
    References
    ----------
    .. [1] Russoniello, C. J. and Lautz, L. K. 2020
           Pay the PIED Piper: Guidelines to visualize large geochemical 
           datasets on Piper Diagrams. Groundwater, 58(3): 464-469.
           http://dx.doi.org/10.1111/gwat.12953
    """
    # Basic data check 
    # -------------------------------------------------------------------------
    # Determine if the required geochemical parameters are defined. 
    if not {'Ca', 'Mg', 'Na', 'K', 
            'HCO3', 'CO3', 'Cl', 'SO4'}.issubset(df.columns):
        raise RuntimeError("""
        Trilinear Piper diagram requires geochemical parameters:
        Ca, Mg, Na, K, HCO3, CO3, Cl, and SO4.
        Confirm that these parameters are provided in the input file.""")
        
    # Determine if the provided unit is allowed
    ALLOWED_UNITS = ['mg/L', 'meq/L']
    if unit not in ALLOWED_UNITS:
        raise RuntimeError("""
        Currently only mg/L and meq/L are supported.
        Convert the unit manually if needed.""")
        
    # Global plot settings
    # -------------------------------------------------------------------------
    # mpl.rcParams['lines.linewidth'] = 1
    mpl.rcParams['lines.markersize'] = 6
    
    # Change default settings for figures
    plt.style.use('default')
    plt.rcParams['font.size'] = 10
    plt.rcParams['axes.labelsize'] = 10
    plt.rcParams['axes.labelweight'] = 'bold'
    plt.rcParams['axes.titlesize'] = 10
    plt.rcParams['xtick.labelsize'] = 10
    plt.rcParams['ytick.labelsize'] = 10
    plt.rcParams['legend.fontsize'] = 10
    plt.rcParams['figure.titlesize'] = 10   
    
    # Plot background settings
    # -------------------------------------------------------------------------
    # Define the offset between the diamond and traingle
    offset = 0.10 
    offsety = offset * np.tan(np.pi / 3.0)
    h = 0.5 * np.tan(np.pi / 3.0)
    
    # Calculate the traingles' location 
    ltriangle_x = np.array([0, 0.5, 1, 0])
    ltriangle_y = np.array([0, h, 0, 0])
    rtriangle_x = ltriangle_x + 2 * offset + 1
    rtriangle_y = ltriangle_y
    
    # Calculate the diamond's location 
    diamond_x = np.array([0.5, 1, 1.5, 1, 0.5]) + offset
    diamond_y = h * (np.array([1, 2, 1, 0, 1])) + (offset * np.tan(np.pi / 3))
    
    # Plot the traingles and diamond
    fig = plt.figure(figsize=(10,10), dpi=100)
    ax = fig.add_subplot(111, aspect='equal', frameon=False, xticks=[], yticks=[])
    ax.plot(ltriangle_x, ltriangle_y, '-k', lw=1.0)
    ax.plot(rtriangle_x, rtriangle_y, '-k', lw=1.0)
    ax.plot(diamond_x, diamond_y, '-k', lw=1.0)
    
    # Plot the lines with the interval of 20%
    interval = 0.2
    ticklabels = ['0', '20', '40', '60', '80', '100']
    for i, x in enumerate(np.linspace(0, 1, int(1/interval+1))):
        # the left traingle
        ax.plot([x, x - x / 2.0], 
                [0, x / 2.0 * np.tan(np.pi / 3)], 
                'k:', lw=1.0)
        ## the bottom ticks
        if i in [1, 2, 3, 4]: 
            ax.text(x, 0-0.03, ticklabels[-i-1], 
                    ha='center', va='center')
        ax.plot([x, (1-x)/2.0+x], 
                 [0, (1-x)/2.0*np.tan(np.pi/3)], 
                 'k:', lw=1.0)
        ## the right ticks
        if i in [1, 2, 3, 4]:
            ax.text((1-x)/2.0+x + 0.026, (1-x)/2.0*np.tan(np.pi/3) + 0.015, ticklabels[i], ha='center', va='center', rotation=-60)
        ax.plot([x/2, 1-x/2], 
                [x/2*np.tan(np.pi/3), x/2*np.tan(np.pi/3)], 
                'k:', lw=1.0)
        ## the left ticks
        if i in [1, 2, 3, 4]:
            ax.text(x/2 - 0.026, x/2*np.tan(np.pi/3) + 0.015, ticklabels[i], 
                    ha='center', va='center', rotation=60)
        
        # the right traingle
        ax.plot([x+1+2*offset, x-x/2.0+1+2*offset], 
                [0, x/2.0*np.tan(np.pi/3)], 
                'k:', lw=1.0)
        ## the bottom ticks
        if i in [1, 2, 3, 4]:
            ax.text(x+1+2*offset, 0-0.03, ticklabels[i], 
                    ha='center', va='center')
        ax.plot([x+1+2*offset, (1-x)/2.0+x+1+2*offset],
                 [0, (1-x)/2.0*np.tan(np.pi/3)], 
                 'k:', lw=1.0)
        ## the right ticks
        if i in [1, 2, 3, 4]:
            ax.text((1-x)/2.0+x+1+2*offset  + 0.026, (1-x)/2.0*np.tan(np.pi/3) + 0.015, ticklabels[-i-1], 
                    ha='center', va='center', rotation=-60)
        ax.plot([x/2+1+2*offset, 1-x/2+1+2*offset], 
                [x/2*np.tan(np.pi/3), x/2*np.tan(np.pi/3)], 
                'k:', lw=1.0)
        ## the left ticks
        if i in [1, 2, 3, 4]:
            ax.text(x/2+1+2*offset - 0.026, x/2*np.tan(np.pi/3) + 0.015, ticklabels[-i-1], 
                    ha='center', va='center', rotation=60)
        
        # the diamond
        ax.plot([0.5+offset+0.5/(1/interval)*x/interval, 1+offset+0.5/(1/interval)*x/interval], 
                 [h+offset*np.tan(np.pi/3)+0.5/(1/interval)*x/interval*np.tan(np.pi/3), offset*np.tan(np.pi/3)+0.5/(1/interval)*x/interval*np.tan(np.pi/3)], 
                 'k:', lw=1.0)
        ## the upper left and lower right
        if i in [1, 2, 3, 4]: 
            ax.text(0.5+offset+0.5/(1/interval)*x/interval  - 0.026, h+offset*np.tan(np.pi/3)+0.5/(1/interval)*x/interval*np.tan(np.pi/3) + 0.015, ticklabels[i], 
                    ha='center', va='center', rotation=60)
            ax.text(1+offset+0.5/(1/interval)*x/interval + 0.026, offset*np.tan(np.pi/3)+0.5/(1/interval)*x/interval*np.tan(np.pi/3) - 0.015, ticklabels[-i-1], 
                    ha='center', va='center', rotation=60)
        ax.plot([0.5+offset+0.5/(1/interval)*x/interval, 1+offset+0.5/(1/interval)*x/interval], 
                 [h+offset*np.tan(np.pi/3)-0.5/(1/interval)*x/interval*np.tan(np.pi/3), 2*h+offset*np.tan(np.pi/3)-0.5/(1/interval)*x/interval*np.tan(np.pi/3)], 
                 'k:', lw=1.0)
        ## the lower left and upper right
        if i in [1, 2, 3, 4]:  
            ax.text(0.5+offset+0.5/(1/interval)*x/interval- 0.026, h+offset*np.tan(np.pi/3)-0.5/(1/interval)*x/interval*np.tan(np.pi/3) - 0.015, ticklabels[i], 
                    ha='center', va='center', rotation=-60)
            ax.text(1+offset+0.5/(1/interval)*x/interval + 0.026, 2*h+offset*np.tan(np.pi/3)-0.5/(1/interval)*x/interval*np.tan(np.pi/3) + 0.015, ticklabels[-i-1], 
                    ha='center', va='center', rotation=-60)
    
    # Labels and title
    plt.text(0.5, -offset, '%' + '$Ca^{2+}$', 
             ha='center', va='center', fontsize=12)
    plt.text(1+2*offset+0.5, -offset, '%' + '$Cl^{-}$', 
            ha='center', va='center', fontsize=12)
    plt.text(0.25-offset*np.cos(np.pi/30), 0.25*np.tan(np.pi/3)+offset*np.sin(np.pi/30), '%' + '$Mg^{2+}$',  
             ha='center', va='center', rotation=60, fontsize=12)
    plt.text(1.75+2*offset+offset*np.cos(np.pi/30), 0.25*np.tan(np.pi/3)+offset*np.sin(np.pi/30), '%' + '$SO_4^{2-}$',  
              ha='center', va='center', rotation=-60, fontsize=12)
    plt.text(0.75+offset*np.cos(np.pi/30), 0.25*np.tan(np.pi/3)+offset*np.sin(np.pi/30), '%' + '$Na^+$' + '+%' + '$K^+$',  
              ha='center', va='center', rotation=-60, fontsize=12)
    plt.text(1+2*offset+0.25-offset*np.cos(np.pi/30), 0.25*np.tan(np.pi/3)+offset*np.sin(np.pi/30), '%' + '$HCO_3^-$' + '+%' + '$CO_3^{2-}$',  
              ha='center', va='center', rotation=60, fontsize=12)
    
    plt.text(0.5+offset+0.5*offset+offset*np.cos(np.pi/30), h+offset*np.tan(np.pi/3)+0.25*np.tan(np.pi/3)+offset*np.sin(np.pi/30), '%' + '$SO_4^{2-}$' + '+%' + '$Cl^-$',  
              ha='center', va='center', rotation=60, fontsize=12)
    plt.text(1.5+offset-0.25+offset*np.cos(np.pi/30), h+offset*np.tan(np.pi/3)+0.25*np.tan(np.pi/3)+offset*np.sin(np.pi/30), '%' + '$Ca^{2+}$' + '+%' + '$Mg^{2+}$', 
              ha='center', va='center', rotation=-60, fontsize=12)
    
     # Convert unit if needed
    if unit == 'mg/L':
        gmol = np.array([ions_WEIGHT['Ca'], 
                         ions_WEIGHT['Mg'], 
                         ions_WEIGHT['Na'], 
                         ions_WEIGHT['K'], 
                         ions_WEIGHT['HCO3'],
                         ions_WEIGHT['CO3'], 
                         ions_WEIGHT['Cl'], 
                         ions_WEIGHT['SO4']])
    
        eqmol = np.array([ions_CHARGE['Ca'], 
                          ions_CHARGE['Mg'], 
                          ions_CHARGE['Na'], 
                          ions_CHARGE['K'], 
                          ions_CHARGE['HCO3'], 
                          ions_CHARGE['CO3'], 
                          ions_CHARGE['Cl'], 
                          ions_CHARGE['SO4']])
    
        tmpdf = df[['Ca', 'Mg', 'Na', 'K', 'HCO3', 'CO3', 'Cl', 'SO4']]
        dat = tmpdf.values
        
        meqL = (dat / abs(gmol)) * abs(eqmol)
        
    elif unit == 'meq/L':
        meqL = df[['Ca', 'Mg', 'Na', 'K', 'HCO3', 'CO3', 'Cl', 'SO4']].values
    
    else:
        raise RuntimeError("""
        Currently only mg/L and meq/L are supported.
        Convert the unit if needed.""")
    
    # Calculate the percentages
    sumcat = np.sum(meqL[:, 0:4], axis=1)
    suman = np.sum(meqL[:, 4:8], axis=1)
    cat = np.zeros((dat.shape[0], 3))
    an = np.zeros((dat.shape[0], 3))
    cat[:, 0] = meqL[:, 0] / sumcat                  # Ca
    cat[:, 1] = meqL[:, 1] / sumcat                  # Mg
    cat[:, 2] = (meqL[:, 2] + meqL[:, 3]) / sumcat   # Na+K
    an[:, 0] = (meqL[:, 4] + meqL[:, 5]) / suman     # HCO3 + CO3
    an[:, 2] = meqL[:, 6] / suman                    # Cl
    an[:, 1] = meqL[:, 7] / suman                    # SO4

    # Convert into cartesian coordinates
    cat_x = 0.5 * (2 * cat[:, 2] + cat[:, 1])
    cat_y = h * cat[:, 1]
    an_x = 1 + 2 * offset + 0.5 * (2 * an[:, 2] + an[:, 1])
    an_y = h * an[:, 1]
    d_x = an_y / (4 * h) + 0.5 * an_x - cat_y / (4 * h) + 0.5 * cat_x
    d_y = 0.5 * an_y + h * an_x + 0.5 * cat_y - h * cat_x
      
    # Kernel density estimation
    from sklearn.neighbors import KernelDensity
    from matplotlib.path import Path
    
    nbins = 500
    cmap = 'Reds'
    
    kde = KernelDensity(kernel='gaussian', 
                        bandwidth=0.05,
                        metric='euclidean')
    
    x = np.linspace(0,  1 + 2 * offset + 1, nbins)
    y = np.linspace(0,  h * 2 + (offset * np.tan(np.pi / 3)), nbins)
    xx, yy = np.meshgrid(x, y)
    points = np.vstack((xx.flatten(), yy.flatten())).T
    
    # The left triangle
    tupVerts = [(0, 0), 
                (0.5, h), 
                (1, 0), 
                (0,0)]
    kde.fit(np.vstack((cat_x, cat_y)).T)
    p = Path(tupVerts)
    grid = p.contains_points(points)
    mask = grid.reshape(nbins, nbins).flatten()
    
    z = np.exp(kde.score_samples(points))
    z[np.where(mask==False)] = -9999
    zz = z.reshape(xx.shape)
    
    plt.contourf(xx, yy, zz, 
                 levels=np.linspace(0, z.max(), 50), 
                 cmap=cmap)
    
    # The right triangle
    tupVerts = [(1 + 2 * offset, 0), 
                (1 + 2 * offset + 0.5, h), 
                (2 + 2 * offset, 0), 
                (1 + 2 * offset, 0)]
    kde.fit(np.vstack((an_x, an_y)).T)
    p = Path(tupVerts)
    grid = p.contains_points(points)
    mask = grid.reshape(nbins, nbins).flatten()
    
    z = np.exp(kde.score_samples(points))
    z[np.where(mask==False)] = -9999
    zz = z.reshape(xx.shape)
    
    plt.contourf(xx, yy, zz, levels=np.linspace(0, z.max(), 50), 
                 cmap=cmap)
    
    # The central diamond
    tupVerts = [(0.5 + offset, h + offset * np.tan(np.pi / 3)), 
                (1.0 + offset, 2 * h + offset * np.tan(np.pi / 3)), 
                (1.5 + offset, h + offset * np.tan(np.pi / 3)), 
                (1.0 + offset, offset * np.tan(np.pi / 3)),
                (0.5 + offset, h + offset * np.tan(np.pi / 3))]
    kde.fit(np.vstack((d_x, d_y)).T)
    p = Path(tupVerts)
    grid = p.contains_points(points)
    mask = grid.reshape(nbins, nbins).flatten()

    z = np.exp(kde.score_samples(points))
    z[np.where(mask==False)] = -9999
    zz = z.reshape(xx.shape)
    
    cf = plt.contourf(xx, yy, zz, levels=np.linspace(0, z.max(), 100), 
                      cmap=cmap)
    
    cb = plt.colorbar(cf, extend='both', spacing='uniform',
                      orientation='vertical', fraction=0.025, pad=0.05)
    
    cb.ax.set_ylabel('$Density$', rotation=90, labelpad=-75, fontsize=14)
    cb.ax.set_yticks([0, z.max()])
    cb.ax.set_yticklabels(['Low', 'High'], fontsize=12)
    
    '''
    # Plot the scatters
    Labels = []
    for i in range(len(df)):
        if (df.at[i, 'Label'] in Labels or df.at[i, 'Label'] == ''):
            TmpLabel = ''
        else:
            TmpLabel = df.at[i, 'Label']
            Labels.append(TmpLabel)
    
        try:
            plt.scatter(cat_x[i], cat_y[i], 
                        marker=df.at[i, 'Marker'],
                        s=df.at[i, 'Size'], 
                        color=df.at[i, 'Color'], 
                        alpha=df.at[i, 'Alpha'],
                        #label=TmpLabel, 
                        edgecolors='black')
            plt.scatter(an_x[i], an_y[i], 
                        marker=df.at[i, 'Marker'],
                        s=df.at[i, 'Size'], 
                        color=df.at[i, 'Color'], 
                        alpha=df.at[i, 'Alpha'],
                        label=TmpLabel, 
                        edgecolors='black')
            plt.scatter(d_x[i], d_y[i], 
                        marker=df.at[i, 'Marker'],
                        s=df.at[i, 'Size'], 
                        color=df.at[i, 'Color'], 
                        alpha=df.at[i, 'Alpha'],
                        #label=TmpLabel, 
                        edgecolors='black')
        except(ValueError):
                pass
    '''
    
    # Display the info
    cwd = os.getcwd()
    print("Contour-filed Piper plot created. Saving it to %s \n" %cwd)
    
    # Save the figure
    plt.savefig(figname + '.' + figformat, format=figformat, 
                bbox_inches='tight', dpi=300)
    
    return

if __name__ == '__main__':
    # Example data
    '''
    data = {'Sample' : ['sample1', 'sample2', 'sample3', 'sample4', 'sample5', 'sample6'],
            'Label'  : ['C1', 'C2', 'C2', 'C3', 'C3', 'C1'],
            'Color'  : ['red', 'green', 'green', 'blue', 'blue', 'red'],
            'Marker' : ['o', 'o', 'o', 'o', 'o', 'o'],
            'Size'   : [30, 30, 30, 30, 30, 30],
            'Alpha'  : [0.6, 0.6, 0.6, 0.6, 0.6, 0.6],
            'pH'     : [7.8, 7.6, 7.5, 7.7, 7.4, 7.1],
            'Ca'     : [32, 46, 54, 50, 50, 134],
            'Mg'     : [6, 11, 11, 11, 22, 21],
            'Na'     : [28, 17, 16, 25, 25, 39],
            'K'      : [2.8, 0.7, 2.4, 2.8, 0.5, 6.4],
            'HCO3'   : [73, 201, 207, 244, 305, 275],
            'CO3'    : [0, 0, 0, 0, 0, 0],
            'Cl'     : [43, 14, 18, 18, 11, 96],
            'SO4'    : [48, 9, 10, 9, 9, 100],
            'TDS'    : [233, 299, 377, 360, 424, 673],
            }

    df = pd.DataFrame(data)
    # df = pd.read_csv('../data/data_template.csv')
    '''
    df = pd.read_csv('../data/Moreno_Merino _2021_Fig2b_dataset.csv')
    plot(df, unit='mg/L', figname='contour-filled Piper diagram', figformat='jpg')
    
    
    
    